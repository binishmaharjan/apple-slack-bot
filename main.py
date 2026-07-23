import os
import re
import requests

WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL")

APPLE_NEWS_URL = "https://developer.apple.com/news/"
APPLE_NEWS_BASE = "https://developer.apple.com"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

ARTICLE_PATTERN = re.compile(
    r'<a class="article-title" href="(/news/\?id=[^"]+)"><h2>([^<]+)</h2></a>'
)

def fetch_latest_apple_news():
    print(f"Fetching Apple Developer News from {APPLE_NEWS_URL}...")

    response = requests.get(APPLE_NEWS_URL, headers=HEADERS, timeout=15)
    print(f"HTTP Status Code: {response.status_code}")

    if response.status_code != 200:
        raise RuntimeError(f"❌ Failed to fetch Apple Developer News. Server returned HTTP status {response.status_code}")

    match = ARTICLE_PATTERN.search(response.text)
    if not match:
        raise RuntimeError("❌ Could not find any news articles on the Apple Developer News page.")

    path, title = match.groups()
    return title.strip(), f"{APPLE_NEWS_BASE}{path}"

def check_apple_news():
    if not WEBHOOK_URL:
        raise ValueError("❌ SLACK_WEBHOOK_URL environment variable is missing or empty!")

    title, link = fetch_latest_apple_news()

    print(f"Latest Article Title: '{title}'")
    print("Posting to Slack...")

    payload = {
        "text": f"📢 *Latest Apple Developer News*\n*<{link}|{title}>*"
    }

    res = requests.post(WEBHOOK_URL, json=payload, timeout=10)

    if res.status_code != 200:
        raise RuntimeError(f"❌ Slack Webhook rejected the message. Status: {res.status_code}, Response: {res.text}")

    print("✅ Successfully posted to Slack!")

if __name__ == "__main__":
    check_apple_news()
