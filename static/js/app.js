// ===============================
// CONFIG
// ===============================
const API_BASE = "http://localhost:5000";

// APP STATE
let currentNews = [];
let isLoading = false;

// DOM ELEMENTS
const searchInput = document.getElementById("searchInput");
const searchBtn = document.getElementById("searchBtn");
const scrapeBtn = document.getElementById("scrapeBtn");
const scrapeSelector = document.getElementById("scrapeSelector");
const newsGrid = document.getElementById("newsGrid");
const loading = document.getElementById("loading");
const emptyState = document.getElementById("emptyState");
const totalNewsCount = document.getElementById("totalNewsCount");
const sourcesCount = document.getElementById("sourcesCount");

// ===============================
// GLOBAL SOURCE FOR SEARCH
// ===============================
let selectedSource = "geo"; // Default selected source

// Detect source selection
document.querySelectorAll(".source-btn").forEach((btn) => {
    btn.addEventListener("click", function () {
        document.querySelectorAll(".source-btn").forEach((b) => b.classList.remove("active"));
        this.classList.add("active");
        selectedSource = this.dataset.source;
        console.log("Selected source:", selectedSource);
    });
});

// INIT
document.addEventListener("DOMContentLoaded", () => {
    loadAllNews();
    searchBtn.addEventListener("click", handleSearch);
    scrapeBtn.addEventListener("click", handleScrape);

    searchInput.addEventListener("keypress", (e) => {
        if (e.key === "Enter") handleSearch();
    });
});

// ===============================
// LOAD ALL NEWS
// ===============================
async function loadAllNews() {
    setLoading(true);
    try {
        const res = await fetch(`${API_BASE}/news?limit=200`);
        const data = await res.json();
        currentNews = data;

        displayNews(data);
        updateStats(data);

        showToast("News loaded successfully!", "success");
    } catch (err) {
        console.error(err);
        showToast("Unable to load news.", "error");
        showEmptyState();
    } finally {
        setLoading(false);
    }
}

// ===============================
// SEARCH NEWS (LIVE SCRAPE)
// ===============================
async function handleSearch() {
    const query = searchInput.value.trim();

    if (!query) {
        showToast("Please enter a search query.", "error");
        return;
    }

    if (!selectedSource) {
        showToast("Please select a news source!", "error");
        return;
    }

    setLoading(true);

    try {
        console.log(`Searching → ${selectedSource}`);

        const res = await fetch(
            `${API_BASE}/search?query=${encodeURIComponent(query)}&source=${selectedSource}`
        );

        const data = await res.json();

        if (data.error) {
            showToast(data.error, "error");
            return;
        }

        currentNews = data.results || [];
        displayNews(currentNews);
        updateStats(currentNews);

        if (currentNews.length === 0) {
            showToast(`No results found for "${query}"`, "error");
        } else {
            showToast(`Found ${currentNews.length} articles`, "success");
        }
    } catch (err) {
        console.error(err);
        showToast("Search failed. Try again.", "error");
    } finally {
        setLoading(false);
    }
}

// ===============================
// MANUAL SCRAPE (single source)
// ===============================
async function handleScrape() {
    const source = scrapeSelector.value || "geo";

    showToast(`Scraping ${source.toUpperCase()} news...`, "success");
    setLoading(true);

    try {
        const res = await fetch(`${API_BASE}/scrape?source=${source}`);
        const data = await res.json();

        if (data.error || data.status !== "success") {
            showToast("Scraping failed.", "error");
            return;
        }

        showToast(`Scraped ${data.count} articles from ${source.toUpperCase()}.`, "success");

        await loadAllNews();
    } catch (err) {
        console.error(err);
        showToast("Scraping failed. Server may be busy.", "error");
    } finally {
        setLoading(false);
    }
}

// ===============================
// DISPLAY NEWS
// ===============================
function displayNews(newsArray) {
    if (!newsArray || newsArray.length === 0) {
        showEmptyState();
        return;
    }

    emptyState.style.display = "none";
    newsGrid.style.display = "grid";

    newsGrid.innerHTML = newsArray.map((news) => createNewsCard(news)).join("");
}

// ===============================
// NEWS CARD TEMPLATE
// ===============================
function createNewsCard(news) {
    const imgURL = news.picture || "https://via.placeholder.com/400x200?text=No+Image";
    const heading = news.heading || "No Title";
    const summary = news.blog || "No summary available";
    const url = news.url || "#";
    const source = formatSource(news.source);

    return `
        <div class="news-card">
            <img src="${imgURL}" 
                 class="news-image"
                 onerror="this.src='https://via.placeholder.com/400x200?text=Image+Not+Available'">

            <div class="news-content">
                <h3 class="news-heading">${heading}</h3>
                <p class="news-summary">${truncate(summary, 180)}</p>

                <div class="news-footer">
                    <span class="news-source">${source}</span>
                    <a href="${url}" target="_blank" class="read-more">
                        Read Full Article
                    </a>
                </div>
            </div>
        </div>
    `;
}

function formatSource(source) {
    if (!source) return "Unknown";
    return source.charAt(0).toUpperCase() + source.slice(1);
}

// ===============================
// STATS
// ===============================
function updateStats(newsArray) {
    totalNewsCount.textContent = newsArray.length;
    const uniqueSources = new Set(newsArray.map((n) => n.source));
    sourcesCount.textContent = uniqueSources.size;
}

// ===============================
// UTILITIES
// ===============================
function truncate(text, maxLength) {
    if (!text || text.length <= maxLength) return text;
    return text.substring(0, maxLength) + "...";
}

function showEmptyState() {
    newsGrid.style.display = "none";
    emptyState.style.display = "block";
}

function setLoading(state) {
    isLoading = state;
    if (state) {
        loading.classList.add("active");
        searchBtn.disabled = true;
        scrapeBtn.disabled = true;
    } else {
        loading.classList.remove("active");
        searchBtn.disabled = false;
        scrapeBtn.disabled = false;
    }
}

// ===============================
// TOAST NOTIFICATIONS
// ===============================
function showToast(message, type = "success") {
    const existing = document.querySelector(".toast");
    if (existing) existing.remove();

    const toast = document.createElement("div");
    toast.className = `toast ${type}`;
    toast.textContent = message;

    document.body.appendChild(toast);

    setTimeout(() => toast.classList.add("show"), 50);

    setTimeout(() => {
        toast.classList.remove("show");
        setTimeout(() => toast.remove(), 300);
    }, 3000);
}
