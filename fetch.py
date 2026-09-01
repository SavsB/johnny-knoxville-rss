import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, urlparse

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
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;"
        "q=0.9,image/avif,image/webp,*/*;q=0.8"
    ),
}


def clean_text(text):
    """Clean whitespace and HTML-ish text."""

    if not text:
        return ""

    text = BeautifulSoup(text, "html.parser").get_text(" ", strip=True)
    text = re.sub(r"\s+", " ", text)

    return text.strip()


def shorten(text, length=300):
    """Create a short RSS description."""

    text = clean_text(text)

    if len(text) <= length:
        return text

    return text[:length].rsplit(" ", 1)[0] + "…"


def load_posts():
    if DATA_FILE.exists():
        try:
            return json.loads(
                DATA_FILE.read_text(encoding="utf-8")
            )
        except Exception:
            pass

    return []


def save_posts(posts):
    DATA_FILE.write_text(
        json.dumps(
            posts,
            indent=2,
            ensure_ascii=False
        ),
        encoding="utf-8"
    )


def extract_tumblr_data(html):
    """
    Extract post URLs and useful text from Tumblr's search HTML.

    Tumblr has changed its search page structure several times,
    so this intentionally uses several extraction methods.
    """

    results = {}

    soup = BeautifulSoup(html, "html.parser")

    # ---------------------------------------------------------
    # 1. Normal links
    # ---------------------------------------------------------

    for link in soup.find_all("a", href=True):

        href = link.get("href", "")

        if "/post/" not in href:
            continue

        if not href.startswith("http"):
            continue

        href = href.split("?")[0]

        text = clean_text(link.get_text(" ", strip=True))

        if not text:
            text = "Johnny Knoxville Tumblr post"

        results[href] = {
            "link": href,
            "title": text[:200],
            "description": text[:500],
        }

    # ---------------------------------------------------------
    # 2. Embedded JSON / raw HTML
    # ---------------------------------------------------------

    patterns = [
        r'https?://[A-Za-z0-9_-]+\.tumblr\.com/post/\d+',
        r'https?://www\.tumblr\.com/[A-Za-z0-9_-]+/\d+',
    ]

    for pattern in patterns:

        for match in re.findall(pattern, html):

            url = match.replace("\\/", "/")
            url = url.split("?")[0]

            if url not in results:

                results[url] = {
                    "link": url,
                    "title": "Johnny Knoxville Tumblr post",
                    "description": (
                        "Johnny Knoxville Tumblr search result."
                    ),
                }

    # ---------------------------------------------------------
    # 3. Look for nearby useful text
    # ---------------------------------------------------------

    for url, item in results.items():

        # Find elements containing the post URL
        elements = soup.find_all(
            href=lambda href: href and url in href
        )

        for element in elements:

            parent = element

            # Search a few levels upward for a useful container
            for _ in range(4):

                if parent is None:
                    break

                text = clean_text(
                    parent.get_text(" ", strip=True)
                )

                if len(text) > len(item["description"]):

                    item["description"] = shorten(
                        text,
                        500
                    )

                    # Try to find a heading
                    heading = parent.find(
                        ["h1", "h2", "h3", "h4", "h5"]
                    )

                    if heading:

                        heading_text = clean_text(
                            heading.get_text(
                                " ",
                                strip=True
                            )
                        )

                        if heading_text:
                            item["title"] = (
                                heading_text[:200]
                            )

                    break

                parent = parent.parent

    return list(results.values())


def fetch_query(query):

    encoded = quote(query)

    url = (
        f"https://www.tumblr.com/search/"
        f"{encoded}"
    )

    print()
    print(f"Searching Tumblr: {query}")

    try:

        response = requests.get(
            url,
            headers=HEADERS,
            timeout=30
        )

        print(
            f"HTTP status: {response.status_code}"
        )

        print(
            f"Downloaded: {len(response.text)} bytes"
        )

        response.raise_for_status()

        results = extract_tumblr_data(
            response.text
        )

        print(
            f"Found {len(results)} possible posts"
        )

        return results

    except Exception as exc:

        print(
            f"ERROR searching '{query}': {exc}"
        )

        return []


def create_feed(posts):

    OUTPUT_DIR.mkdir(
        exist_ok=True
    )

    feed = FeedGenerator()

    feed.id(SITE_URL)

    feed.title(
        "Johnny Knoxville Fanfiction — Tumblr"
    )

    feed.link(
        href=(
            "https://www.tumblr.com/"
            "search/johnny%20knoxville%20x%20reader"
        ),
        rel="alternate"
    )

    feed.link(
        href=f"{SITE_URL}feed.xml",
        rel="self"
    )

    feed.description(
        "Tumblr search results for Johnny Knoxville "
        "fanfiction, x-reader, imagines and related posts."
    )

    feed.language("en")

    for post in posts[:100]:

        entry = feed.add_entry()

        title = post.get(
            "title",
            "Johnny Knoxville Tumblr post"
        )

        description = post.get(
            "description",
            "Johnny Knoxville Tumblr search result."
        )

        link = post["link"]

        # Avoid generic duplicate-looking titles
        if not title or len(title) < 4:
            title = (
                "Johnny Knoxville Tumblr post"
            )

        entry.id(link)

        entry.title(title)

        entry.link(
            href=link
        )

        rss_description = (
            f"{description}<br><br>"
            f"<a href=\"{link}\">"
            f"Read this post on Tumblr →"
            f"</a>"
        )

        entry.description(
            rss_description
        )

        published = post.get(
            "published"
        )

        if published:

            try:

                dt = datetime.fromisoformat(
                    published.replace(
                        "Z",
                        "+00:00"
                    )
                )

                entry.pubDate(dt)

            except Exception:
                pass

    feed.rss_file(
        str(OUTPUT_FILE)
    )


def create_index():

    OUTPUT_DIR.mkdir(
        exist_ok=True
    )

    html = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Johnny Knoxville Tumblr RSS</title>
</head>

<body>

<h1>Johnny Knoxville Tumblr RSS</h1>

<p>
This feed collects Tumblr search results for
Johnny Knoxville fanfiction, x-reader,
imagines and related posts.
</p>

<p>
<a href="feed.xml">
Open RSS Feed
</a>
</p>

</body>
</html>
"""

    (
        OUTPUT_DIR / "index.html"
    ).write_text(
        html,
        encoding="utf-8"
    )


def main():

    existing = load_posts()

    posts_by_url = {}

    # ---------------------------------------------------------
    # Keep everything we've already found
    # ---------------------------------------------------------

    for post in existing:

        if "link" in post:

            posts_by_url[
                post["link"]
            ] = post

    # ---------------------------------------------------------
    # Search Tumblr
    # ---------------------------------------------------------

    new_results = []

    for query in QUERIES:

        results = fetch_query(
            query
        )

        new_results.extend(
            results
        )

    # ---------------------------------------------------------
    # Merge new results
    # ---------------------------------------------------------

    now = datetime.now(
        timezone.utc
    ).isoformat()

    for result in new_results:

        link = result["link"]

        if link in posts_by_url:

            # Improve existing metadata if
            # the newer search result has it.

            existing_post = posts_by_url[
                link
            ]

            if (
                result.get("title")
                and
                result["title"]
                != "Johnny Knoxville Tumblr post"
            ):

                existing_post["title"] = (
                    result["title"]
                )

            if (
                result.get("description")
                and
                len(result["description"])
                >
                len(
                    existing_post.get(
                        "description",
                        ""
                    )
                )
            ):

                existing_post["description"] = (
                    result["description"]
                )

        else:

            posts_by_url[link] = {

                "link": link,

                "title": result.get(
                    "title",
                    "Johnny Knoxville Tumblr post"
                ),

                "description": result.get(
                    "description",
                    "Johnny Knoxville Tumblr search result."
                ),

                "published": now,
            }

    posts = list(
        posts_by_url.values()
    )

    # ---------------------------------------------------------
    # Sort newest discovered first
    # ---------------------------------------------------------

    posts.sort(
        key=lambda post:
        post.get(
            "published",
            ""
        ),
        reverse=True
    )

    # ---------------------------------------------------------
    # Keep database manageable
    # ---------------------------------------------------------

    posts = posts[:500]

    save_posts(posts)

    create_feed(posts)

    create_index()

    print()
    print("=" * 60)
    print(
        f"TOTAL POSTS IN DATABASE: {len(posts)}"
    )
    print(
        f"RESULTS FOUND THIS RUN: {len(new_results)}"
    )
    print("=" * 60)


if __name__ == "__main__":
    main()
