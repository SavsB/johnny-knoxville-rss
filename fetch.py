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
        print(f"Could not read posts.json: {e}")

    return []


def save_posts(posts):
    with open(POSTS_FILE, "w", encoding="utf-8") as f:
        json.dump(
            posts,
            f,
            indent=2,
            ensure_ascii=False
        )


def clean_text(text):
    if not text:
        return ""

    text = html.unescape(str(text))
    text = re.sub(r"\s+", " ", text)

    return text.strip()


def find_posts(data):
    """
    Recursively search Tumblr's JSON for objects
    representing posts.
    """

    posts = []

    if isinstance(data, dict):

        if (
            data.get("objectType") == "post"
            and data.get("postUrl")
        ):
            posts.append(data)

        for value in data.values():
            posts.extend(find_posts(value))

    elif isinstance(data, list):

        for item in data:
            posts.extend(find_posts(item))

    return posts


def get_post_title(post):

    summary = clean_text(
        post.get("summary", "")
    )

    if summary:
        return summary[:200]

    content = post.get("content", [])

    if isinstance(content, list):

        for block in content:

            if (
                isinstance(block, dict)
                and block.get("type") == "text"
            ):

                text = clean_text(
                    block.get("text", "")
                )

                if text:
                    return text[:200]

    slug = clean_text(
        post.get("slug", "")
    )

    if slug:
        return slug.replace("-", " ")[:200]

    return "Tumblr post"


def extract_initial_state(html_text):

    soup = BeautifulSoup(
        html_text,
        "html.parser"
    )

    script = soup.find(
        "script",
        {
            "id": "___INITIAL_STATE___",
            "type": "application/json"
        }
    )

    if not script:
        print(
            "Could not find "
            "___INITIAL_STATE___ JSON."
        )
        return None

    try:
        return json.loads(script.string)

    except Exception as e:
        print(
            f"Could not parse initial JSON: {e}"
        )
        return None


def search_tumblr(query):

    url = (
        "https://www.tumblr.com/search/"
        + quote(query)
    )

    print()
    print("=" * 50)
    print(f"Searching: {query}")
    print(f"URL: {url}")

    try:

        response = requests.get(
            url,
            headers=HEADERS,
            timeout=30
        )

        print(
            f"HTTP status: "
            f"{response.status_code}"
        )

        print(
            f"Response length: "
            f"{len(response.text)}"
        )

        with open(
            "tumblr_debug.html",
            "w",
            encoding="utf-8"
        ) as f:
            f.write(response.text)

        if response.status_code != 200:
            print("Search request failed.")
            return []

        state = extract_initial_state(
            response.text
        )

        if not state:
            return []

        raw_posts = find_posts(state)

        print(
            f"Found {len(raw_posts)} "
            f"possible posts in JSON."
        )

        results = []
        seen = set()

        for post in raw_posts:

            post_url = post.get(
                "postUrl",
                ""
            )

            if not post_url:
                continue

            post_url = post_url.split("?")[0]

            if post_url in seen:
                continue

            seen.add(post_url)

            results.append({
                "url": post_url,
                "title": get_post_title(post),
                "query": query,
                "timestamp": post.get(
                    "timestamp",
                    0
                ),
                "blog": post.get(
                    "blogName",
                    ""
                ),
            })

        print(
            f"Found {len(results)} "
            f"unique posts."
        )

        return results

    except Exception as e:

        print(
            f"Search error: {e}"
        )

        return []


def merge_posts(existing, new_posts):

    posts_by_url = {}

    # Add all existing posts first.
    for post in existing:

        url = post.get("url")

        if url:
            posts_by_url[url] = post

    new_count = 0

    # Add only genuinely new posts.
    for post in new_posts:

        url = post.get("url")

        if not url:
            continue

        if url not in posts_by_url:

            post["added"] = datetime.now(
                timezone.utc
            ).isoformat()

            posts_by_url[url] = post
            new_count += 1

        else:

            # Keep the old post, but improve missing information.
            existing_post = posts_by_url[url]

            new_title = post.get("title", "")

            if (
                new_title
                and new_title != "Tumblr post"
                and (
                    not existing_post.get("title")
                    or existing_post.get("title") == "Tumblr post"
                )
            ):
                existing_post["title"] = new_title

            if (
                not existing_post.get("timestamp")
                and post.get("timestamp")
            ):
                existing_post["timestamp"] = post["timestamp"]

            if (
                not existing_post.get("blog")
                and post.get("blog")
            ):
                existing_post["blog"] = post["blog"]

    posts = list(posts_by_url.values())

    # Sort newest Tumblr posts first.
    posts.sort(
        key=lambda post: int(
            post.get("timestamp", 0) or 0
        ),
        reverse=True
    )

    print(f"New posts added: {new_count}")

    # IMPORTANT:
    # Do not accidentally shrink the database.
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
        "Tumblr posts related to Johnny Knoxville, "
        "x Reader, fanfiction and imagines."
    )

    ET.SubElement(
        channel,
        "language"
    ).text = "en"

    ET.SubElement(
        channel,
        "{http://www.w3.org/2005/Atom}link",
        {
            "href": (
                "https://savsb.github.io/"
                "johnny-knoxville-rss/feed.xml"
            ),
            "rel": "self",
            "type": "application/rss+xml"
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
            "guid",
            {"isPermaLink": "true"}
        ).text = url

        description_parts = []

        blog = post.get("blog", "")

        if blog:
            description_parts.append(
                f"Blog: {blog}"
            )

        query = post.get("query", "")

        if query:
            description_parts.append(
                f"Found via: {query}"
            )

        ET.SubElement(
            item,
            "description"
        ).text = " | ".join(
            description_parts
        )

        timestamp = post.get(
            "timestamp",
            0
        )

        if timestamp:

            try:

                dt = datetime.fromtimestamp(
                    int(timestamp),
                    tz=timezone.utc
                )

                ET.SubElement(
                    item,
                    "pubDate"
                ).text = dt.strftime(
                    "%a, %d %b %Y %H:%M:%S +0000"
                )

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
            post.get("url", ""),
            quote=True
        )

        blog = html.escape(
            post.get("blog", "")
        )

        rows.append(
            f"""
<li>
<a href="{url}" target="_blank" rel="noopener">
{title}
</a>
<br>
<small>{blog}</small>
</li>
"""
        )

    page = f"""<!DOCTYPE html>
<html lang="en">

<head>

<meta charset="UTF-8">

<meta
name="viewport"
content="width=device-width, initial-scale=1.0">

<title>
Johnny Knoxville Tumblr RSS Feed
</title>

</head>

<body>

<h1>
Johnny Knoxville Tumblr RSS Feed
</h1>

<p>
Automatically collected Tumblr search results.
</p>

<p>
<a href="feed.xml">
Subscribe to the RSS Feed
</a>
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
    print("=" * 50)

    print(
        f"TOTAL RESULTS FOUND: "
        f"{total_found}"
    )

    print("=" * 50)

    # Important safety feature:
    # Never erase your database if Tumblr
    # suddenly returns no results.

    if total_found == 0:

        print(
            "WARNING: Zero Tumblr results found."
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

    print()

    print(
        f"TOTAL POSTS IN DATABASE: "
        f"{len(posts)}"
    )

    make_rss(posts)
    make_index(posts)

    print()
    print("===== COMPLETE =====")


if __name__ == "__main__":
    main()
