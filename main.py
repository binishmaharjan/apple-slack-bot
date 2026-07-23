import os
import requests
import feedparser

WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL")
FEED_URL = "https://developer.apple.com/news/rss/news.rss"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
}

def check_apple_news():
    if not WEBHOOK_URL:
        print("Error: SLACK_WEBHOOK_URL variable is missing.")
        return

    try:
        response = requests.get(FEED_URL, headers=HEADERS, timeout=10)
        feed = feedparser.parse(response.content)
    except Exception as e:
        print(f"Failed to fetch RSS: {e}")
        return

    if feed.entries:
        latest = feed.entries[0]
        title = latest.title.strip()
        link = latest.link.strip()

        payload = {
            "text": f"📢 *Latest Apple Developer News*\n*<{link}|{title}>*"
        }

        res = requests.post(WEBHOOK_URL, json=payload, timeout=10)
        if res.status_code == 200:
            print(f"Successfully posted to Slack: {title}")
        else:
            print(f"Slack post failed: {res.status_code}")

if __name__ == "__main__":
    check_apple_news()
