from selenium import webdriver
from selenium.webdriver.common.by import By
from bs4 import BeautifulSoup
from flask import Flask, jsonify, request, render_template
from flask_cors import CORS
from transformers import pipeline
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.common.exceptions import TimeoutException, WebDriverException
import sqlite3
import time
import threading
import logging
import atexit
import os
from typing import List, Dict, Optional
import glob
import requests

# ------------------- Optional local cache paths (safe to remove/change) -------------------
os.environ.setdefault("TRANSFORMERS_CACHE", "D:/AI_CACHE/huggingface")
os.environ.setdefault("HF_HOME", "D:/AI_CACHE/huggingface")
os.environ.setdefault("TORCH_HOME", "D:/AI_CACHE/torch")
# -----------------------------------------------------------------------------------------

# ------------------- Configuration -------------------
MAX_ARTICLES = 50
DATABASE_FILE = "realify_news.db"

REQUEST_TIMEOUT = 15
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0 Safari/537.36"
)

# ------------------- Logging Setup -------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("realify_news")

# ------------------- Summarization Model (lazy, shared) -------------------
_summarizer = None
_summarizer_lock = threading.Lock()


def load_models_with_caching():
    """
    Loads a lightweight Hugging Face summarization model.
    Called once inside get_summarizer().
    """
    global _summarizer

    try:
        logger.info("⚡ Loading lightweight T5-small summarization model...")

        # Smaller and faster than BART / DistilBART
        _summarizer = pipeline(
            "summarization",
            model="t5-small",
            tokenizer="t5-small",
        )

        logger.info("✅ T5-small summarization model loaded successfully!")

    except Exception as e:
        logger.error(f"❌ Error loading summarization model: {e}")
        logger.warning("⚠️ App will run but summarization will fall back to truncation.")


def get_summarizer():
    """Thread-safe lazy initializer for the summarization pipeline."""
    global _summarizer
    if _summarizer is None:
        with _summarizer_lock:
            if _summarizer is None:
                load_models_with_caching()
    return _summarizer


def _chunk_text(text: str, max_chars: int = 700) -> List[str]:
    """
    Naive char-based chunking with sentence boundaries where possible.
    """
    text = " ".join(text.split())  # normalize whitespace
    if len(text) <= max_chars:
        return [text]

    chunks = []
    current = []

    for sentence in text.split(". "):
        sentence = sentence.strip()
        if not sentence:
            continue
        candidate = (". ".join(current + [sentence])).strip()
        if len(candidate) <= max_chars:
            current.append(sentence)
        else:
            if current:
                chunks.append(". ".join(current).strip())
            current = [sentence]

    if current:
        chunks.append(". ".join(current).strip())

    return chunks


def summarize_text(text: str) -> str:
    """
    Chunk-based summarization:
    - For short text: return as is.
    - For longer text: summarize chunks, then summarize combined summary.
    - If model isn't available: safe truncation fallback.
    """
    if not text:
        return ""

    text = " ".join(text.split())
    if len(text) <= 400:
        # Already short enough to show
        return text

    summarizer = get_summarizer()
    if summarizer is None:
        logger.warning("Summarizer unavailable, using truncation fallback.")
        return (text[:800] + "...") if len(text) > 800 else text

    try:
        chunks = _chunk_text(text, max_chars=700)
        partial_summaries = []

        for chunk in chunks:
            try:
                summary = summarizer(
                    chunk,
                    max_length=120,
                    min_length=40,
                    do_sample=False,
                    truncation=True,
                )[0]["summary_text"]
                partial_summaries.append(summary.strip())
            except Exception as e:
                logger.warning(f"Summarization error on chunk: {e}")
                partial_summaries.append(chunk[:300])

        combined = " ".join(partial_summaries)
        combined = " ".join(combined.split())

        if len(combined) <= 500:
            return combined

        # Final pass to compress overall summary
        try:
            final_summary = summarizer(
                combined,
                max_length=150,
                min_length=50,
                do_sample=False,
                truncation=True,
            )[0]["summary_text"]
            return final_summary.strip()
        except Exception as e2:
            logger.warning(f"Final summarization pass failed: {e2}")
            return (combined[:800] + "...") if len(combined) > 800 else combined

    except Exception as e:
        logger.error(f"Unexpected summarization error: {e}")
        return (text[:800] + "...") if len(text) > 800 else text


# ------------------- Database Manager -------------------
class DatabaseManager:
    def __init__(self, db_file: str):
        self.db_file = db_file
        self._init_db()

    def _connect(self):
        # Allow access from multiple threads
        return sqlite3.connect(self.db_file, check_same_thread=False)

    def _init_db(self):
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS headlinesData (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source TEXT,
                    url TEXT UNIQUE,
                    picture TEXT,
                    heading TEXT,
                    blog TEXT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """
            )
            conn.commit()
            logger.info("✅ Database initialized")

    def save_headline(self, headline_data: Dict):
        if not headline_data or "url" not in headline_data:
            return

        with self._connect() as conn:
            try:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO headlinesData 
                    (url, source, picture, heading, blog)
                    VALUES (?, ?, ?, ?, ?)
                """,
                    (
                        headline_data.get("url"),
                        headline_data.get("source", "unknown"),
                        headline_data.get("picture"),
                        headline_data.get("heading"),
                        headline_data.get("blog"),
                    ),
                )
                conn.commit()
            except sqlite3.Error as e:
                logger.error(f"Database error saving headline: {e}")

    def get_all_headlines(self, limit: int = MAX_ARTICLES) -> List[Dict]:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT url, source, picture, heading, blog 
                FROM headlinesData 
                ORDER BY timestamp DESC 
                LIMIT ?
            """,
                (limit,),
            )
            return [dict(row) for row in cursor.fetchall()]


# ------------------- Helper: HTTP Fetching -------------------
def fetch_html(url: str) -> Optional[str]:
    try:
        resp = requests.get(
            url,
            headers={"User-Agent": USER_AGENT},
            timeout=REQUEST_TIMEOUT,
        )
        if resp.status_code == 200:
            return resp.text
        logger.warning(f"Non-200 status {resp.status_code} for {url}")
    except Exception as e:
        logger.error(f"Request error for {url}: {e}")
    return None


# ------------------- Selenium / ChromeDriver Setup -------------------

CHROME_DRIVER_PATH: Optional[str] = None
_chromedriver_lock = threading.Lock()


def _init_chromedriver() -> str:
    """
    Initialize ChromeDriver.
    1) Prefer the explicit local path: D:\\Chromedriver\\chromedriver.exe
    2) If not found, try WebDriverManager once.
    3) Finally, fall back to 'chromedriver' in PATH.
    """
    global CHROME_DRIVER_PATH
    if CHROME_DRIVER_PATH:
        return CHROME_DRIVER_PATH

    with _chromedriver_lock:
        if CHROME_DRIVER_PATH:
            return CHROME_DRIVER_PATH

        # 1) YOUR LOCAL CHROMEDRIVER PATH
        local_path = r"D:\Chromedriver\chromedriver.exe"
        if os.path.exists(local_path):
            logger.info(f"🚀 Using local ChromeDriver at: {local_path}")
            CHROME_DRIVER_PATH = local_path
            return CHROME_DRIVER_PATH
        else:
            logger.warning(f"Local ChromeDriver not found at: {local_path}")

        # 2) TRY WEBDRIVERMANAGER
        try:
            logger.info("🔧 Initializing ChromeDriver via WebDriverManager...")
            path = ChromeDriverManager().install()

            if not path.lower().endswith(".exe"):
                base_dir = os.path.dirname(path)
                candidates = glob.glob(os.path.join(base_dir, "chromedriver*.exe"))
                if candidates:
                    path = candidates[0]
                    logger.info(f"✅ Resolved ChromeDriver executable: {path}")
                else:
                    raise RuntimeError(
                        f"ChromeDriverManager returned non-executable path: {path}"
                    )

            CHROME_DRIVER_PATH = path
            logger.info(f"✅ Using ChromeDriver at: {CHROME_DRIVER_PATH}")
            return CHROME_DRIVER_PATH

        except Exception as e:
            logger.error(f"❌ Failed to initialize ChromeDriver via WebDriverManager: {e}")
            # 3) FALLBACK TO 'chromedriver' ON PATH
            CHROME_DRIVER_PATH = "chromedriver"
            logger.info("⚠️ Falling back to 'chromedriver' from PATH.")
            return CHROME_DRIVER_PATH


# ------------------- News Scraper -------------------
class NewsScraper:
    def __init__(self):
        # No long-lived driver; we create per-scrape for stability
        pass

    # ------------- Selenium Driver (for Geo homepage/search) -------------
    def _create_driver(self):
        options = webdriver.ChromeOptions()
        # Use stable headless mode instead of "--headless=new"
        options.add_argument("--headless")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument(f"user-agent={USER_AGENT}")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)

        driver_path = _init_chromedriver()
        try:
            driver = webdriver.Chrome(
                service=Service(driver_path),
                options=options,
            )
        except WebDriverException as e:
            logger.error(f"❌ WebDriverException when starting Chrome: {e}")
            raise

        driver.set_page_load_timeout(REQUEST_TIMEOUT)
        return driver

    # ------------- Geo News (search) -------------
    def _process_geo_article(self, url: str) -> Optional[Dict]:
        html = fetch_html(url)
        if not html:
            return None

        soup = BeautifulSoup(html, "html.parser")

        # Heading
        heading = "No Heading"
        heading_element = soup.find("div", class_="heading_H")
        if heading_element:
            h1 = heading_element.find("h1")
            if h1:
                heading = h1.get_text(strip=True)

        if heading == "No Heading":
            h1_tag = soup.find("h1")
            if h1_tag:
                heading = h1_tag.get_text(strip=True)

        # Image
        image = None
        content_area = soup.find("div", class_="content-area")
        if content_area:
            img_tag = content_area.find("img")
            if img_tag and img_tag.get("src"):
                image = img_tag["src"]

        if not image:
            og_image = soup.find("meta", property="og:image")
            if og_image and og_image.get("content"):
                image = og_image["content"]

        # Text
        text = ""
        if content_area:
            paragraphs = content_area.find_all("p")
            text = " ".join(
                p.get_text(strip=True) for p in paragraphs if p.get_text(strip=True)
            )

        if not text:
            article_body = soup.find("article") or soup.find("div", class_="story-detail")
            if article_body:
                paragraphs = article_body.find_all("p")
                text = " ".join(
                    p.get_text(strip=True)
                    for p in paragraphs
                    if p.get_text(strip=True)
                )

        if not text or len(text) < 50:
            logger.warning(f"⚠️  [Geo] Not enough text content for {url}")
            return None

        summary = summarize_text(text)

        return {
            "source": "geo",
            "url": url,
            "picture": image,
            "heading": heading,
            "blog": summary,
        }

    def search_geo_news(self, query: str) -> List[Dict]:
        """
        Search Geo News for specific query using their search page.
        """
        logger.info(f"🔍 [Geo] Searching for: '{query}'")
        try:
            driver = self._create_driver()
        except Exception as e:
            logger.error(f"Failed to initialize Selenium driver for search: {e}")
            return []

        article_links = set()
        try:
            search_url = f"https://www.geo.tv/search/{query.replace(' ', '+')}"
            try:
                driver.get(search_url)
            except TimeoutException:
                logger.error(f"❌ Timeout while loading Geo search page for '{query}'")
                return []

            time.sleep(3)

            soup = BeautifulSoup(driver.page_source, "html.parser")
            links = soup.find_all("a", href=True)
            for link in links:
                href = link["href"]
                if "/latest/" in href:
                    if href.startswith("https://www.geo.tv"):
                        article_links.add(href)
                    elif href.startswith("/"):
                        article_links.add("https://www.geo.tv" + href)
        except Exception as e:
            logger.error(f"Search error for '{query}' on Geo: {e}")
        finally:
            try:
                driver.quit()
            except Exception:
                pass

        logger.info(f"[Geo] Found {len(article_links)} articles for query: {query}")
        headlines: List[Dict] = []
        for href in list(article_links)[:10]:
            try:
                headline = self._process_geo_article(href)
                if headline:
                    headlines.append(headline)
            except Exception as e:
                logger.error(f"[Geo] Error processing search article {href}: {e}")
        return headlines

    # ------------- BBC News -------------
    def _process_bbc_article(self, url: str) -> Optional[Dict]:
        html = fetch_html(url)
        if not html:
            return None
        soup = BeautifulSoup(html, "html.parser")

        heading = "No Heading"
        h1 = soup.find("h1")
        if h1:
            heading = h1.get_text(strip=True)

        image = None
        og_image = soup.find("meta", property="og:image")
        if og_image and og_image.get("content"):
            image = og_image["content"]

        text = ""
        # BBC often uses data-component="text-block"
        text_blocks = soup.find_all(attrs={"data-component": "text-block"})
        if text_blocks:
            text = " ".join(
                blk.get_text(strip=True)
                for blk in text_blocks
                if blk.get_text(strip=True)
            )
        if not text:
            paragraphs = soup.find_all("p")
            text = " ".join(
                p.get_text(strip=True)
                for p in paragraphs
                if p.get_text(strip=True)
            )

        if not text or len(text) < 50:
            logger.warning(f"⚠️  [BBC] Not enough text for {url}")
            return None

        summary = summarize_text(text)
        return {
            "source": "bbc",
            "url": url,
            "picture": image,
            "heading": heading,
            "blog": summary,
        }

    def search_bbc_news(self, query: str) -> List[Dict]:
        logger.info(f"🔍 [BBC] Searching for: '{query}'")
        search_url = f"https://www.bbc.co.uk/search?q={query.replace(' ', '+')}&filter=news"
        html = fetch_html(search_url)
        if not html:
            return []

        soup = BeautifulSoup(html, "html.parser")
        links = set()

        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "/news/" in href and href.startswith("https://www.bbc.co.uk"):
                links.add(href.replace("https://www.bbc.co.uk", "https://www.bbc.com"))

        logger.info(f"[BBC] Found {len(links)} search results")
        headlines: List[Dict] = []
        for href in list(links)[:10]:
            try:
                article = self._process_bbc_article(href)
                if article:
                    headlines.append(article)
            except Exception as e:
                logger.error(f"[BBC] Error processing search result {href}: {e}")
        return headlines

    # ------------- ARY News -------------
    def _process_ary_article(self, url: str) -> Optional[Dict]:
        html = fetch_html(url)
        if not html:
            return None
        soup = BeautifulSoup(html, "html.parser")

        heading = "No Heading"
        h1 = soup.find("h1")
        if h1:
            heading = h1.get_text(strip=True)

        image = None
        og_image = soup.find("meta", property="og:image")
        if og_image and og_image.get("content"):
            image = og_image["content"]

        text = ""
        # Try typical post content container
        content = soup.find("div", class_="td-post-content")
        if content:
            paragraphs = content.find_all("p")
            text = " ".join(
                p.get_text(strip=True)
                for p in paragraphs
                if p.get_text(strip=True)
            )

        # Fallback to all paragraphs
        if not text:
            paragraphs = soup.find_all("p")
            text = " ".join(
                p.get_text(strip=True)
                for p in paragraphs
                if p.get_text(strip=True)
            )

        if not text or len(text) < 50:
            logger.warning(f"⚠️  [ARY] Not enough text for {url}")
            return None

        summary = summarize_text(text)
        return {
            "source": "ary",
            "url": url,
            "picture": image,
            "heading": heading,
            "blog": summary,
        }

    def search_ary_news(self, query: str) -> List[Dict]:
        logger.info(f"🔍 [ARY] Searching for: '{query}'")

        # Primary new-style search URL
        search_url = f"https://arynews.tv/search/{query.replace(' ', '%20')}"
        html = fetch_html(search_url)

        # Fallback to older WordPress style
        if not html:
            fallback_url = f"https://arynews.tv/?s={query.replace(' ', '+')}"
            logger.info(f"🔄 [ARY] Trying fallback search: {fallback_url}")
            html = fetch_html(fallback_url)

        if not html:
            logger.error("❌ ARY search failed (no HTML from primary or fallback)")
            return []

        soup = BeautifulSoup(html, "html.parser")
        links = set()

        for a in soup.find_all("a", href=True):
            href = a["href"]

            # Normalize relative URLs
            if href.startswith("/"):
                href = "https://arynews.tv" + href

            # Filter likely article links
            if not href.startswith("https://arynews.tv"):
                continue
            if any(
                x in href
                for x in [
                    "/category/",
                    "/tag/",
                    "/videos",
                    "/video",
                    "/live",
                    "/author/",
                    "/elections",
                ]
            ):
                continue

            links.add(href)

        logger.info(f"[ARY] Found {len(links)} search results")
        headlines: List[Dict] = []
        for href in list(links)[:10]:
            try:
                article = self._process_ary_article(href)
                if article:
                    headlines.append(article)
            except Exception as e:
                logger.error(f"[ARY] Error processing search result {href}: {e}")
        return headlines

    # ------------- Samaa News -------------
    def _process_samaa_article(self, url: str) -> Optional[Dict]:
        html = fetch_html(url)
        if not html:
            return None
        soup = BeautifulSoup(html, "html.parser")

        heading = "No Heading"
        h1 = soup.find("h1")
        if h1:
            heading = h1.get_text(strip=True)

        image = None
        og_image = soup.find("meta", property="og:image")
        if og_image and og_image.get("content"):
            image = og_image["content"]

        text = ""
        content = soup.find("div", class_="story-content") or soup.find(
            "div", class_="news-detail"
        )
        if content:
            paragraphs = content.find_all("p")
            text = " ".join(
                p.get_text(strip=True)
                for p in paragraphs
                if p.get_text(strip=True)
            )

        if not text:
            paragraphs = soup.find_all("p")
            text = " ".join(
                p.get_text(strip=True)
                for p in paragraphs
                if p.get_text(strip=True)
            )

        if not text or len(text) < 50:
            logger.warning(f"⚠️  [Samaa] Not enough text for {url}")
            return None

        summary = summarize_text(text)
        return {
            "source": "samaa",
            "url": url,
            "picture": image,
            "heading": heading,
            "blog": summary,
        }

    def search_samaa_news(self, query: str) -> List[Dict]:
        logger.info(f"🔍 [Samaa] Searching for: '{query}'")
        search_url = f"https://www.samaa.tv/search/{query.replace(' ', '%20')}"
        html = fetch_html(search_url)
        if not html:
            return []

        soup = BeautifulSoup(html, "html.parser")
        links = set()

        for a in soup.find_all("a", href=True):
            href = a["href"]
            if href.startswith("/"):
                href = "https://www.samaa.tv" + href

            if not href.startswith("https://www.samaa.tv"):
                continue
            if "/news/" not in href and "/pakistan/" not in href and "/latest-news/" not in href:
                continue

            links.add(href)

        logger.info(f"[Samaa] Found {len(links)} search results")
        headlines: List[Dict] = []
        for href in list(links)[:10]:
            try:
                article = self._process_samaa_article(href)
                if article:
                    headlines.append(article)
            except Exception as e:
                logger.error(f"[Samaa] Error processing search result {href}: {e}")
        return headlines

    # ------------- Dawn News -------------
    def _process_dawn_article(self, url: str) -> Optional[Dict]:
        html = fetch_html(url)
        if not html:
            return None
        soup = BeautifulSoup(html, "html.parser")

        heading = "No Heading"
        h1 = soup.find("h1")
        if h1:
            heading = h1.get_text(strip=True)

        image = None
        og_image = soup.find("meta", property="og:image")
        if og_image and og_image.get("content"):
            image = og_image["content"]

        text = ""
        content = soup.find("div", class_="story__content") or soup.find(
            "div", class_="story__body"
        )
        if content:
            paragraphs = content.find_all("p")
            text = " ".join(
                p.get_text(strip=True)
                for p in paragraphs
                if p.get_text(strip=True)
            )

        if not text:
            paragraphs = soup.find_all("p")
            text = " ".join(
                p.get_text(strip=True)
                for p in paragraphs
                if p.get_text(strip=True)
            )

        if not text or len(text) < 50:
            logger.warning(f"⚠️  [Dawn] Not enough text for {url}")
            return None

        summary = summarize_text(text)
        return {
            "source": "dawn",
            "url": url,
            "picture": image,
            "heading": heading,
            "blog": summary,
        }

    def search_dawn_news(self, query: str) -> List[Dict]:
        logger.info(f"🔍 [Dawn] Searching for: '{query}'")
        search_url = (
            "https://www.dawn.com/search?"
            "cx=partner-pub-2646044137506720%3A7244554279&cof=FORID%3A10&ie=UTF-8&"
            f"q={query.replace(' ', '+')}"
        )
        html = fetch_html(search_url)
        if not html:
            return []

        soup = BeautifulSoup(html, "html.parser")
        links = set()

        for a in soup.find_all("a", href=True):
            href = a["href"]
            if href.startswith("/"):
                href = "https://www.dawn.com" + href

            if not href.startswith("https://www.dawn.com"):
                continue
            if "/news/" not in href and "/latest-news/" not in href:
                continue

            links.add(href)

        logger.info(f"[Dawn] Found {len(links)} search results")
        headlines: List[Dict] = []
        for href in list(links)[:10]:
            try:
                article = self._process_dawn_article(href)
                if article:
                    headlines.append(article)
            except Exception as e:
                logger.error(f"[Dawn] Error processing search result {href}: {e}")
        return headlines

    # ------------- Search All Sources -------------
    def search_all_sources(self, query: str) -> List[Dict]:
        """Search across all news sources."""
        all_results: List[Dict] = []

        logger.info(f"\n🔍 Searching all sources for: '{query}'")

        # Geo
        logger.info("Searching Geo News...")
        all_results.extend(self.search_geo_news(query))

        # BBC
        logger.info("Searching BBC News...")
        all_results.extend(self.search_bbc_news(query))

        # ARY
        logger.info("Searching ARY News...")
        all_results.extend(self.search_ary_news(query))

        # Samaa
        logger.info("Searching Samaa News...")
        all_results.extend(self.search_samaa_news(query))

        # Dawn
        logger.info("Searching Dawn News...")
        all_results.extend(self.search_dawn_news(query))

        logger.info(f"✅ Total search results found: {len(all_results)}")
        return all_results


# ------------------- Flask App -------------------
app = Flask(__name__)
CORS(app)
db = DatabaseManager(DATABASE_FILE)
scraper = NewsScraper()


@app.route("/", methods=["GET"])
def home():
    return render_template("index.html")


@app.route("/news", methods=["GET"])
def get_news():
    """
    Get latest news from DB (all sources).
    Optional query param: limit=number
    NOTE:
    - Yahan koi scraping trigger nahi hoti.
    - Sirf previously saved articles (search ke zariye) aate hain.
    """
    try:
        limit_param = request.args.get("limit")
        limit = int(limit_param) if limit_param else MAX_ARTICLES
    except ValueError:
        limit = MAX_ARTICLES

    headlines = db.get_all_headlines(limit=limit)
    return jsonify(headlines)


@app.route("/search", methods=["GET"])
def search_news():
    """
    Live search endpoint.

    Query params:
    - query=<text>  (required)
    - source=geo|bbc|ary|samaa|dawn|all  (optional, default: all)

    Behavior:
    - Hamesha live scraping hota hai (no cache, no scheduler).
    - Jo results milte hain woh DB me save bhi ho jate hain.
    """
    query = request.args.get("query", "").strip()
    source = request.args.get("source", "all").lower()

    if not query:
        return jsonify({"error": "Query parameter is required"}), 400

    try:
        if source == "geo":
            results = scraper.search_geo_news(query)
        elif source == "bbc":
            results = scraper.search_bbc_news(query)
        elif source == "ary":
            results = scraper.search_ary_news(query)
        elif source == "samaa":
            results = scraper.search_samaa_news(query)
        elif source == "dawn":
            results = scraper.search_dawn_news(query)
        elif source == "all":
            results = scraper.search_all_sources(query)
        else:
            return jsonify({"error": f"Unknown source '{source}'"}), 400

        for result in results:
            db.save_headline(result)

        return jsonify(
            {
                "status": "success",
                "query": query,
                "source": source,
                "count": len(results),
                "results": results,
            }
        )
    except Exception as e:
        logger.error(f"/search endpoint error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


# Ensure clean shutdown of any shared resources
@atexit.register
def shutdown():
    logger.info("Shutting down Realify News service...")


if __name__ == "__main__":
    # ❌ No startup scraping
    # ❌ No scheduler / background jobs
    app.run(debug=False, host="0.0.0.0", port=5000)
