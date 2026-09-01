import os
import re
import json
import html
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timezone
from urllib.parse import quote
from xml.etree import ElementTree as ET


QUERIES = [
    "johnny knoxville x reader",
    "johnny knoxville reader",
    "johnny knoxville imagine",
    "johnny knoxville fic",
    "johnny knoxville fanfiction",
    "johnny knoxville x oc",
]

POSTS_FILE = "posts.json"
SITE_DIR = "site"
FEED_FILE = os.path.join(SITE_DIR, "feed.xml")
INDEX_FILE = os.path.join(SITE_DIR, "index.html")

MAX_POSTS = 500

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/139.0 Safari/537.36"
    )
}


def load_posts():
    if not os.path.exists(POSTS_FILE):
        return []

    try:
        with open(POSTS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        if isinstance(data, list):
            return data

    except Exception as e:
        print(f"Could not read {POSTS_FILE}: {e}")

    return []


def save_posts(posts):
    with open(POSTS_FILE, "w", encoding="utf-8") as f:
        json.dump(posts, f, indent=2, ensure_ascii=False)


def clean_text(text):
    if not text:
        return ""

    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def extract_post_links(soup):
    """
    Extract Tumblr post URLs using the same general approach
    as the scraper that previously found the 115 posts.
    """

    found = set()

    for tag in soup.find_all(href=True):

        href = tag.get("href", "")

        if not href:
            continue

        # Absolute Tumblr URL
        if href.startswith("https://www.tumblr.com/"):
            url = href

        # Relative Tumblr URL
        elif href.startswith("/"):
            url = "https://www.tumblr.com" + href

        else:
            continue

        # Tumblr post URLs
        if "/post/" in url:
            url = url.split("?")[0]
            url = url.split("#")[0]

            found.add(url)

    return list(found)


def get_title(link):
    """
    Try to get useful text associated with the post link.
    """

    # Text directly inside the link
    text = clean_text(link.get_text(" ", strip=True))

    if text and len(text) > 3:
        return text[:200]

    # Try nearby parent text
    parent = link.parent

    if parent:
        text = clean_text(
            parent.get_text(" ", strip=True)
        )

        if text and len(text) > 3:
            return text[:200]

    return "Tumblr post"


def search_tumblr(query):
    url = (
        "https://www.tumblr.com/search/"
        + quote(query)
    )

    print()
    print(f"Searching: {query}")
    print(f"URL: {url}")

    try:
        response = requests.get(
            url,
            headers=HEADERS,
            timeout=30
        )

        print(f"HTTP status: {response.status_code}")

        if response.status_code != 200:
            print("Search request failed.")
            return []

        soup = BeautifulSoup(
            response.text,
            "html.parser"
        )

        # Use the working post-link extraction method.
        post_urls = extract_post_links(soup)

        print(
            f"Found {len(post_urls)} post URLs."
        )

        results = []

        # Locate the corresponding anchor so we can
        # attempt to extract useful text.
        for url in post_urls:

            link = soup.find(
                "a",
                href=lambda href:
                    href and (
                        href.split("?")[0].split("#")[0]
                        == url
                    )
            )

            title = get_title(link) if link else "Tumblr post"

            results.append({
                "url": url,
                "title": title,
                "query": query,
            })

        return results

    except Exception as e:
        print(f"Search error: {e}")
        return []


def merge_posts(existing, new_posts):

    posts_by_url = {}

    # Keep everything already saved.
    for post in existing:

        url = post.get("url")

        if url:
            posts_by_url[url] = post

    # Add newly discovered posts.
    for post in new_posts:

        url = post.get("url")

        if not url:
            continue

        if url in posts_by_url:

            existing_post = posts_by_url[url]

            # Update title only if we found
            # something more useful.
            new_title = post.get("title", "")
            old_title = existing_post.get("title", "")

            if (
                new_title
                and new_title != "Tumblr post"
                and (
                    not old_title
                    or old_title == "Tumblr post"
                )
            ):
                existing_post["title"] = new_title

        else:

            post["added"] = datetime.now(
                timezone.utc
            ).isoformat()

            posts_by_url[url] = post

    posts = list(posts_by_url.values())

    # Newest discovered posts first.
    posts.sort(
        key=lambda x: x.get("added", ""),
        reverse=True
    )

    return posts[:MAX_POSTS]


def make_rss(posts):

    os.makedirs(
        SITE_DIR,
        exist_ok=True
    )

    rss = ET.Element(
        "rss",
        {
            "version": "2.0",
            "xmlns:atom":
                "http://www.w3.org/2005/Atom"
        }
    )

    channel = ET.SubElement(
        rss,
        "channel"
    )

    ET.SubElement(
        channel,
        "title"
    ).text = (
        "Johnny Knoxville x Reader Tumblr Feed"
    )

    ET.SubElement(
        channel,
        "link"
    ).text = (
        "https://savsb.github.io/"
        "johnny-knoxville-rss/"
    )

    ET.SubElement(
        channel,
        "description"
    ).text = (
        "Tumblr posts related to Johnny Knoxville "
        "x Reader, fanfiction, imagines and related searches."
    )

    ET.SubElement(
        channel,
        "language"
    ).text = "en"

    ET.SubElement(
        channel,
        "generator"
    ).text = "Custom Tumblr RSS Generator"

    ET.SubElement(
        channel,
        "{http://www.w3.org/2005/Atom}link",
        {
            "href":
                "https://savsb.github.io/"
                "johnny-knoxville-rss/feed.xml",
            "rel": "self",
            "type": "application/rss+xml",
        }
    )

    for post in posts:

        item = ET.SubElement(
            channel,
            "item"
        )

        title = post.get(
            "title",
            "Tumblr post"
        )

        url = post.get(
            "url",
            ""
        )

        ET.SubElement(
            item,
            "title"
        ).text = title

        ET.SubElement(
            item,
            "link"
        ).text = url

        ET.SubElement(
            item,
            "guid"
        ).text = url

        ET.SubElement(
            item,
            "description"
        ).text = (
            "Tumblr search: "
            + post.get(
                "query",
                "Johnny Knoxville"
            )
        )

        added = post.get("added")

        if added:

            try:

                dt = datetime.fromisoformat(
                    added.replace(
                        "Z",
                        "+00:00"
                    )
                )

                pubdate = dt.strftime(
                    "%a, %d %b %Y %H:%M:%S +0000"
                )

                ET.SubElement(
                    item,
                    "pubDate"
                ).text = pubdate

            except Exception:
                pass

    tree = ET.ElementTree(rss)

    ET.indent(
        tree,
        space="  "
    )

    tree.write(
        FEED_FILE,
        encoding="utf-8",
        xml_declaration=True
    )

    print(
        f"RSS feed created with "
        f"{len(posts)} posts."
    )


def make_index(posts):

    os.makedirs(
        SITE_DIR,
        exist_ok=True
    )

    rows = []

    for post in posts:

        title = html.escape(
            post.get(
                "title",
                "Tumblr post"
            )
        )

        url = html.escape(
            post.get(
                "url",
                ""
            ),
            quote=True
        )

        query = html.escape(
            post.get(
                "query",
                ""
            )
        )

        rows.append(
            f"""
<li>
<a href="{url}" target="_blank">
{title}
</a>
<small> — {query}</small>
</li>
"""
        )

    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport"
content="width=device-width, initial-scale=1.0">
<title>Johnny Knoxville Tumblr RSS Feed</title>
</head>

<body>

<h1>Johnny Knoxville Tumblr RSS Feed</h1>

<p>
Automatically collected Tumblr search results.
</p>

<p>
<a href="feed.xml">RSS Feed</a>
</p>

<p>
Posts currently stored:
<strong>{len(posts)}</strong>
</p>

<ul>
{''.join(rows)}
</ul>

</body>
</html>
"""

    with open(
        INDEX_FILE,
        "w",
        encoding="utf-8"
    ) as f:
        f.write(page)


def main():

    print(
        "===== JOHNNY KNOXVILLE "
        "TUMBLR RSS ====="
    )

    existing = load_posts()

    print(
        f"Existing posts: "
        f"{len(existing)}"
    )

    all_new = []

    for query in QUERIES:

        results = search_tumblr(query)

        all_new.extend(results)

    total_found = len(all_new)

    print()
    print(
        f"Total newly discovered results: "
        f"{total_found}"
    )

    # SAFETY CHECK:
    #
    # If Tumblr gives us zero results,
    # DO NOT destroy the existing database.
    if total_found == 0:

        print()
        print(
            "WARNING: Tumblr returned "
            "zero results."
        )

        print(
            "Keeping existing posts.json "
            "unchanged."
        )

        posts = existing

    else:

        posts = merge_posts(
            existing,
            all_new
        )

        save_posts(posts)

    print(
        f"Total stored posts: "
        f"{len(posts)}"
    )

    make_rss(posts)
    make_index(posts)

    print()
    print(
        "===== COMPLETE ====="
    )


if __name__ == "__main__":
    main()
