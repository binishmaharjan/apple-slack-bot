import os
import time
import requests
import feedparser

WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL")
FEED_URL = "https://developer.apple.com/news/rss/news.rss"

# Full header set to mimic desktop Safari on macOS
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Connection": "keep-alive"
}

def fetch_feed():
    """Fetch RSS with retries to handle temporary 500s or rate limits."""
    for attempt in range(1, 4):
        print(f"Fetching Apple RSS feed (Attempt {attempt}/3)...")
        try:
            response = requests.get(FEED_URL, headers=HEADERS, timeout=15)
            print(f"HTTP Status Code: {response.status_code}")
            
            if response.status_code == 200:
                return response.content
            
            print(f"Server returned {response.status_code}. Retrying in 2 seconds...")
        except Exception as e:
            print(f"Network error on attempt {attempt}: {e}")
            
        time.sleep(2)
        
    raise RuntimeError("❌ Apple server consistently returned errors or blocked the request.")

def check_apple_news():
    if not WEBHOOK_URL:
        raise ValueError("❌ SLACK_WEBHOOK_URL environment variable is missing or empty!")

    content = fetch_feed()

    # Parse RSS content
    feed = feedparser.parse(content)
    print(f"Found {len(feed.entries)} feed entries.")

    if not feed.entries:
        raise RuntimeError("❌ RSS Feed returned 0 entries. Cloudflare or Apple might be filtering this IP.")

    latest = feed.entries[0]
    title = latest.title.strip()
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
