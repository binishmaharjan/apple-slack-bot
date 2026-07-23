import os
import requests
import feedparser

WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL")

# Fetch Apple Developer News via Google News RSS mirror (bypasses Akamai IP block)
GOOGLE_NEWS_APPLE_RSS = "https://news.google.com/rss/search?q=site:developer.apple.com/news&hl=en-US&gl=US&ceid=US:en"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
}

def check_apple_news():
    if not WEBHOOK_URL:
        raise ValueError("❌ SLACK_WEBHOOK_URL environment variable is missing or empty!")

    print("Fetching Apple Developer News via Google News RSS mirror...")
    
    response = requests.get(GOOGLE_NEWS_APPLE_RSS, headers=HEADERS, timeout=15)
    print(f"HTTP Status Code: {response.status_code}")

    if response.status_code != 200:
        raise RuntimeError(f"❌ Failed to fetch feed. Server returned HTTP status {response.status_code}")

    # Parse XML feed content
    feed = feedparser.parse(response.content)
    print(f"Found {len(feed.entries)} feed entries.")

    if not feed.entries:
        raise RuntimeError("❌ Feed returned 0 entries.")

    latest = feed.entries[0]
    title = latest.title.strip()
    
    # Extract the original article link if available, otherwise fallback to the feed link
    link = latest.link.strip()

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
