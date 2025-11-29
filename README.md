Realify - AI-Powered News Analysis Platform
Realify is an AI-powered news analysis platform that fetches news from multiple sources using fast, lightweight HTML-based search (no Selenium) and summarizes all articles using a transformer model (BART-Large CNN).
Each search returns top 3 results per channel with clean AI summaries.

🌟 Features

🔎 Source-Based Search Only — Search Geo, BBC, ARY, Samaa, Dawn

⚡ Ultra Fast (No Selenium) — Pure requests + BeautifulSoup scraping

🤖 AI Summaries — Uses BART (facebook/bart-large-cnn)

🌐 Clean & Modern Web Interface

🧹 Lightweight Backend — No auto-scraping, no heavy processing

📦 Simple SQLite Storage — Optional storing of results

🎯 Top 3 Results per Source — Fast, efficient, relevant

📰 Supported News Sources
Source	Status	Search	Homepage Scrape
Geo News	✅ Active	✅ Working	❌ Removed
BBC News	✅ Active	✅ Working	❌ Removed
ARY News	✅ Active	✅ Working	❌ Removed
Samaa News	✅ Active	✅ Working	❌ Removed
Dawn News	✅ Active	✅ Working	❌ Removed

✔ Only search-based scraping is active
✔ All channels return max 3 articles
✔ Faster and lighter than Selenium version

🚀 Quick Start
Prerequisites

Python 3.8 or higher

~1.5GB free disk space (AI model)

No Chrome / No Selenium required

Installation

Clone the repo

git clone https://github.com/Hassan-Raza0/AI-News-Summarizer.git
cd Realify

Create virtual environment

python -m venv venv
venv\Scripts\activate  # Windows


Install dependencies

pip install -r requirements.txt


Run the backend
python app.py
Open in browser
http://localhost:5000

🎮 Usage
Web Interface

Select a news channel (Geo / BBC / ARY / Samaa / Dawn / All)

Enter a topic (e.g., "Lahore weather")

Click Search

Realify will:

fetch latest 3 matching articles per source

extract the text

summarize using BART model

show clean results

API Endpoints
# Search specific source
GET /search?query=pakistan&source=geo

# Search all sources
GET /search?query=economy&source=all

# Get stored news (optional)
GET /news

🏗️ Project Structure
Realify/
├── app.py                    # Main Flask backend
├── requirements.txt          # Dependencies
├── templates/
│   └── index.html            # Frontend HTML
├── static/
│   ├── css/style.css         # Styling
│   └── js/app.js             # UI Logic
├── realify_news.db           # SQLite DB (auto-created)
└── README.md

🧠 How It Works
Search Flow
User Search → Selected Channel → Request HTML → Extract Text → AI Summary → Display


✔ No homepage crawling
✔ No Selenium browser
✔ Only direct article scraping via requests

AI Model

Model: facebook/bart-large-cnn

Type: Text Summarization

Chunks long content into pieces

Produces short, clean, readable summaries

⚙️ Configuration

Main config inside app.py:

MAX_PER_SOURCE = 3         # Results per channel
DATABASE_FILE = "realify_news.db"

📊 Tech Stack
Backend

Flask

Requests

BeautifulSoup4

Transformers (BART)

PyTorch

SQLite

Frontend

HTML5 / CSS3

JavaScript

Fetch API

AI

BART-Large-CNN transformer

🐛 Troubleshooting
Slow first-time run

Model download is ~1.5GB

After that → very fast

Empty results

Try a broader query

Some sources have limited search index

📈 Roadmap

 Replace Selenium with pure Requests/BS4

 AI summaries

 Per-channel search

 Limit 3 per channel

 Caching results

 Advanced ranking

 Multi-language summaries

 Mobile app version

👨‍💻 Author

Hassan Raza
GitHub: @Hassan-Raza0

Repo: AI-News-Summarizer
