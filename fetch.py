import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup
from feedgen.feed import FeedGenerator


QUERIES = [
    "johnny knoxville x reader",
    "johnny knoxville reader",
    "johnny knoxville imagine",
    "johnny knoxville fic",
    "johnny knoxville fanfiction",
    "johnny knoxville x oc",
]

SITE_URL = "https://savsb.github.io/johnny-knoxville-rss/"
DATA_FILE = Path("posts.json")
OUTPUT_DIR = Path("site")
OUTPUT_FILE = OUTPUT_DIR / "feed.xml"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def load_posts():
    if DATA_FILE.exists():
        try:
            return json.loads(DATA_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass

    return []


def save_posts(posts):
    DATA_FILE.write_text(
        json.dumps(posts, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )


def extract_post_urls(html):
    """
    Extract Tumblr post URLs from both normal HTML links
    and Tumblr's embedded page data.
    """

    urls = set()

    # Normal HTML links
    soup = BeautifulSoup(html, "html.parser")

    for tag in soup.find_all("a", href=True):
        href = tag.get("href", "")

        if "tumblr.com" in href and "/post/" in href:
            href = href.split("?")[0]
            urls.add(href)

    # Raw HTML / embedded JSON
    patterns = [
        r'https?://[A-Za-z0-9_-]+\.tumblr\.com/post/\d+',
        r'https?://www\.tumblr\.com/[A-Za-z0-9_-]+/\d+',
        r'https?:\\?/\\?/[^"\']+\.tumblr\.com\\?/post\\?/\d+',
    ]

    for pattern in patterns:
        matches = re.findall(pattern, html)

        for url in matches:
            url = url.replace("\\/", "/")
            urls.add(url.split("?")[0])

    return urls


def fetch_query(query):
    encoded = quote(query)
    url = f"https://www.tumblr.com/search/{encoded}"

    print(f"Searching Tumblr: {query}")

    try:
        response = requests.get(
            url,
            headers=HEADERS,
            timeout=30
        )

        print(f"HTTP status: {response.status_code}")
        print(f"Downloaded: {len(response.text)} bytes")

        response.raise_for_status()

        urls = extract_post_urls(response.text)

        print(f"Found {len(urls)} possible posts")

        return urls

    except Exception as exc:
        print(f"ERROR searching '{query}': {exc}")
        return set()


def create_feed(posts):
    OUTPUT_DIR.mkdir(exist_ok=True)

    feed = FeedGenerator()

    feed.id(SITE_URL)
    feed.title("Johnny Knoxville Fanfiction — Tumblr")
    feed.link(
        href="https://www.tumblr.com/search/johnny%20knoxville%20x%20reader",
        rel="alternate"
    )
    feed.link(
        href=f"{SITE_URL}feed.xml",
        rel="self"
    )
    feed.description(
        "Tumblr search results for Johnny Knoxville fanfiction, "
        "x-reader, imagines, and related posts."
    )
    feed.language("en")

    for post in posts[:100]:

        entry = feed.add_entry()

        title = post.get(
            "title",
            "Johnny Knoxville fanfiction — Tumblr"
        )

        entry.id(post["link"])
        entry.title(title)
        entry.link(href=post["link"])

        description = (
            f"Johnny Knoxville fanfiction / x-reader result "
            f"found through Tumblr search.<br><br>"
            f"<a href=\"{post['link']}\">Open Tumblr post</a>"
        )

        entry.description(description)

        published = post.get("published")

        if published:
            try:
                dt = datetime.fromisoformat(
                    published.replace("Z", "+00:00")
                )
                entry.pubDate(dt)
            except Exception:
                pass

    feed.rss_file(str(OUTPUT_FILE))


def create_index():
    OUTPUT_DIR.mkdir(exist_ok=True)

    html = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Johnny Knoxville Tumblr RSS</title>
</head>
<body>
<h1>Johnny Knoxville Tumblr RSS</h1>

<p>
This page provides an RSS feed containing Tumblr search results
for Johnny Knoxville fanfiction, x-reader, imagines, and related posts.
</p>

<p>
<a href="feed.xml">RSS Feed</a>
</p>

</body>
</html>
"""

    (OUTPUT_DIR / "index.html").write_text(
        html,
        encoding="utf-8"
    )


def main():

    existing = load_posts()

    # Existing posts indexed by URL
    posts_by_url = {
        post["link"]: post
        for post in existing
        if "link" in post
    }

    found_urls = set()

    for query in QUERIES:
        found_urls.update(fetch_query(query))

    now = datetime.now(timezone.utc).isoformat()

    for url in found_urls:

        if url not in posts_by_url:

            posts_by_url[url] = {
                "link": url,
                "title": "Johnny Knoxville fanfiction — Tumblr",
                "published": now,
            }

    posts = list(posts_by_url.values())

    # Newest discovered posts first
    posts.sort(
        key=lambda x: x.get("published", ""),
        reverse=True
    )

    # Keep database manageable
    posts = posts[:500]

    save_posts(posts)
    create_feed(posts)
    create_index()

    print()
    print("=" * 50)
    print(f"TOTAL POSTS IN DATABASE: {len(posts)}")
    print(f"NEW POSTS FOUND THIS RUN: {len(found_urls)}")
    print("=" * 50)


if __name__ == "__main__":
    main()
