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


def get_post_title(url, surrounding_text=""):
    """
    Try to create a useful title from text near the Tumblr post link.
    """

    text = clean_text(surrounding_text)

    if text:
        # Avoid extremely long blocks of Tumblr page text.
        if len(text) > 200:
            text = text[:197] + "..."

        return text

    # Fall back to Tumblr URL.
    match = re.search(r"/([^/]+)/(\d+)", url)

    if match:
        blog = match.group(1)
        post_id = match.group(2)
        return f"Tumblr post by {blog} ({post_id})"

    return "Tumblr post"


def search_tumblr(query):
    encoded = quote(query)

    url = f"https://www.tumblr.com/search/{encoded}"

    print(f"\nSearching: {query}")
    print(url)

    try:
        response = requests.get(
            url,
            headers=HEADERS,
            timeout=30
        )

        print(f"HTTP status: {response.status_code}")

        if response.status_code != 200:
            print("Search failed.")
            return []

        soup = BeautifulSoup(response.text, "html.parser")

        results = []

        # Look for Tumblr post links.
        for link in soup.find_all("a", href=True):

            href = link.get("href", "")

            if not href:
                continue

            # Convert relative URLs to absolute.
            if href.startswith("/"):
                full_url = "https://www.tumblr.com" + href
            elif href.startswith("https://www.tumblr.com/"):
                full_url = href
            else:
                continue

            # Tumblr post URLs.
            if "/post/" not in full_url:
                continue

            # Remove query strings/fragments.
            full_url = full_url.split("?")[0].split("#")[0]

            surrounding = ""

            # Try to get useful nearby text.
            parent = link.parent

            if parent:
                surrounding = parent.get_text(" ", strip=True)

            title = get_post_title(full_url, surrounding)

            results.append({
                "url": full_url,
                "title": title,
                "query": query,
            })

        # Deduplicate results from this search.
        unique = {}

        for item in results:
            unique[item["url"]] = item

        results = list(unique.values())

        print(f"Found {len(results)} posts.")

        return results

    except Exception as e:
        print(f"Search error: {e}")
        return []


def merge_posts(existing, new_posts):
    """
    Merge new posts into the existing database without duplicates.
    """

    posts_by_url = {}

    # Existing posts first.
    for post in existing:
        url = post.get("url")

        if url:
            posts_by_url[url] = post

    # New posts overwrite metadata for the same URL.
    for post in new_posts:
        url = post.get("url")

        if not url:
            continue

        if url in posts_by_url:
            old = posts_by_url[url]

            # Keep a better existing title if the new one is generic.
            old_title = old.get("title", "")
            new_title = post.get("title", "")

            if new_title and (
                not old_title
                or old_title.startswith("Tumblr post by ")
            ):
                old["title"] = new_title

            # Keep track of the search term.
            old["query"] = post.get(
                "query",
                old.get("query", "")
            )

        else:
            post["added"] = datetime.now(timezone.utc).isoformat()
            posts_by_url[url] = post

    posts = list(posts_by_url.values())

    # Newest additions first.
    posts.sort(
        key=lambda x: x.get("added", ""),
        reverse=True
    )

    return posts[:MAX_POSTS]


def xml_escape(text):
    return html.escape(str(text), quote=True)


def make_rss(posts):
    os.makedirs(SITE_DIR, exist_ok=True)

    rss = ET.Element(
        "rss",
        {
            "version": "2.0",
            "xmlns:atom": "http://www.w3.org/2005/Atom"
        }
    )

    channel = ET.SubElement(rss, "channel")

    ET.SubElement(
        channel,
        "title"
    ).text = "Johnny Knoxville x Reader Tumblr Feed"

    ET.SubElement(
        channel,
        "link"
    ).text = "https://savsb.github.io/johnny-knoxville-rss/"

    ET.SubElement(
        channel,
        "description"
    ).text = (
        "Tumblr posts related to Johnny Knoxville x Reader, "
        "fanfiction, imagines and related searches."
    )

    ET.SubElement(
        channel,
        "language"
    ).text = "en"

    ET.SubElement(
        channel,
        "generator"
    ).text = "Custom Tumblr RSS Generator"

    # Atom self link.
    ET.SubElement(
        channel,
        "{http://www.w3.org/2005/Atom}link",
        {
            "href": (
                "https://savsb.github.io/"
                "johnny-knoxville-rss/feed.xml"
            ),
            "rel": "self",
            "type": "application/rss+xml",
        }
    )

    for post in posts:

        item = ET.SubElement(channel, "item")

        title = post.get("title", "Tumblr post")
        url = post.get("url", "")

        ET.SubElement(item, "title").text = title
        ET.SubElement(item, "link").text = url
        ET.SubElement(item, "guid").text = url

        description = (
            f"Found through Tumblr search: "
            f"{post.get('query', 'Johnny Knoxville')}"
        )

        ET.SubElement(
            item,
            "description"
        ).text = description

        added = post.get("added")

        if added:
            try:
                dt = datetime.fromisoformat(
                    added.replace("Z", "+00:00")
                )

                timestamp = dt.strftime(
                    "%a, %d %b %Y %H:%M:%S +0000"
                )

                ET.SubElement(
                    item,
                    "pubDate"
                ).text = timestamp

            except Exception:
                pass

    tree = ET.ElementTree(rss)

    ET.indent(tree, space="  ")

    tree.write(
        FEED_FILE,
        encoding="utf-8",
        xml_declaration=True
    )

    print(f"\nRSS feed written to {FEED_FILE}")


def make_index(posts):
    os.makedirs(SITE_DIR, exist_ok=True)

    rows = []

    for post in posts:

        title = html.escape(
            post.get("title", "Tumblr post")
        )

        url = html.escape(
            post.get("url", ""),
            quote=True
        )

        query = html.escape(
            post.get("query", "")
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
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Johnny Knoxville Tumblr RSS Feed</title>
</head>

<body>

<h1>Johnny Knoxville Tumblr RSS Feed</h1>

<p>
This page is automatically generated from Tumblr searches.
</p>

<p>
<a href="feed.xml">RSS Feed</a>
</p>

<p>
Posts currently stored: {len(posts)}
</p>

<ul>
{''.join(rows)}
</ul>

</body>
</html>
"""

    with open(INDEX_FILE, "w", encoding="utf-8") as f:
        f.write(page)

    print(f"Index written to {INDEX_FILE}")


def main():

    print("===== JOHNNY KNOXVILLE TUMBLR RSS =====")

    existing = load_posts()

    print(f"Existing posts: {len(existing)}")

    all_new = []

    for query in QUERIES:
        results = search_tumblr(query)
        all_new.extend(results)

    print(f"\nTotal newly discovered results: {len(all_new)}")

    posts = merge_posts(existing, all_new)

    print(f"Total stored posts: {len(posts)}")

    save_posts(posts)

    make_rss(posts)
    make_index(posts)

    print("\n===== COMPLETE =====")


if __name__ == "__main__":
    main()
