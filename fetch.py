import json
import os
import re
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup
from feedgen.feed import FeedGenerator


SEARCH_QUERY = "johnny knoxville x reader"
SEARCH_URL = f"https://www.tumblr.com/search/{quote(SEARCH_QUERY)}"

OUTPUT_DIR = Path("site")
OUTPUT_FILE = OUTPUT_DIR / "feed.xml"
DATA_FILE = Path("posts.json")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/120 Safari/537.36"
    )
}


def load_existing_posts():
    if DATA_FILE.exists():
        try:
            return json.loads(DATA_FILE.read_text(encoding="utf-8"))
        except Exception:
            return []
    return []


def save_posts(posts):
    DATA_FILE.write_text(
        json.dumps(posts, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )


def get_tumblr_posts():
    response = requests.get(
        SEARCH_URL,
        headers=HEADERS,
        timeout=30
    )

    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")

    posts = []
    seen = set()

    # Look for Tumblr post URLs
    links = soup.find_all("a", href=True)

    for link in links:
        href = link["href"]

        if not href.startswith("http"):
            continue

        # Tumblr post URLs commonly contain /post/
        if "/post/" not in href:
            continue

        # Remove tracking/query parameters
        clean_url = href.split("?")[0]

        if clean_url in seen:
            continue

        seen.add(clean_url)

        text = link.get_text(" ", strip=True)

        if not text:
            text = "Johnny Knoxville x Reader Tumblr Post"

        posts.append({
            "title": text[:200],
            "link": clean_url,
            "description": (
                f"Tumblr search result for: {SEARCH_QUERY}"
            ),
            "published": datetime.now(timezone.utc).isoformat()
        })

    return posts


def create_feed(posts):
    OUTPUT_DIR.mkdir(exist_ok=True)

    fg = FeedGenerator()

    fg.title("Johnny Knoxville x Reader — Tumblr")
    fg.link(href=SEARCH_URL)
    fg.description(
        "Automatically updated Tumblr search results for "
        "Johnny Knoxville x Reader."
    )
    fg.language("en")

    for post in posts[:50]:
        fe = fg.add_entry()

        fe.title(post["title"])
        fe.link(href=post["link"])
        fe.description(post["description"])
        fe.guid(post["link"], permalink=True)

        try:
            dt = datetime.fromisoformat(
                post["published"].replace("Z", "+00:00")
            )
            fe.pubDate(format_datetime(dt))
        except Exception:
            pass

    fg.rss_file(str(OUTPUT_FILE))


def create_homepage():
    homepage = OUTPUT_DIR / "index.html"

    homepage.write_text(
        """<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Johnny Knoxville x Reader RSS</title>
</head>
<body>
    <h1>Johnny Knoxville x Reader — Tumblr RSS Feed</h1>

    <p>
        This feed automatically collects Tumblr search results
        for Johnny Knoxville x Reader.
    </p>

    <p>
        <a href="feed.xml">Open RSS Feed</a>
    </p>
</body>
</html>
""",
        encoding="utf-8"
    )


def main():
    print("Checking Tumblr...")

    existing_posts = load_existing_posts()

    try:
        new_posts = get_tumblr_posts()
    except Exception as e:
        print(f"Error fetching Tumblr: {e}")
        new_posts = []

    # Combine posts without duplicates
    all_posts = {}

    for post in existing_posts + new_posts:
        all_posts[post["link"]] = post

    posts = list(all_posts.values())

    # Keep newest 100
    posts = posts[:100]

    save_posts(posts)

    create_feed(posts)
    create_homepage()

    print(f"Feed created with {len(posts)} posts.")


if __name__ == "__main__":
    main()
