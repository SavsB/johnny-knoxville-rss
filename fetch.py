import os
import re
import json
import html
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timezone
from urllib.parse import quote
from xml.etree import ElementTree as ET


# ============================================================
# SETTINGS
# ============================================================

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

FEED_FILE = os.path.join(
    SITE_DIR,
    "feed.xml"
)

INDEX_FILE = os.path.join(
    SITE_DIR,
    "index.html"
)

MAX_POSTS = 500


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/139.0 Safari/537.36"
    )
}


# ============================================================
# LOAD / SAVE DATABASE
# ============================================================

def load_posts():

    if not os.path.exists(POSTS_FILE):
        return []

    try:

        with open(
            POSTS_FILE,
            "r",
            encoding="utf-8"
        ) as f:

            data = json.load(f)

        if isinstance(data, list):
            return data

    except Exception as e:

        print(
            f"Could not read posts.json: {e}"
        )

    return []


def save_posts(posts):

    with open(
        POSTS_FILE,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            posts,
            f,
            indent=2,
            ensure_ascii=False
        )


# ============================================================
# TEXT CLEANING
# ============================================================

def clean_text(text):

    if not text:
        return ""

    text = html.unescape(
        str(text)
    )

    text = re.sub(
        r"\s+",
        " ",
        text
    )

    return text.strip()


# ============================================================
# FIND TUMBLR POSTS INSIDE INITIAL JSON
# ============================================================

def find_posts(data):

    posts = []

    if isinstance(data, dict):

        if (
            data.get("objectType") == "post"
            and data.get("postUrl")
        ):

            posts.append(data)

        for value in data.values():

            posts.extend(
                find_posts(value)
            )

    elif isinstance(data, list):

        for item in data:

            posts.extend(
                find_posts(item)
            )

    return posts


# ============================================================
# EXTRACT POST TEXT
# ============================================================

def get_post_text(post):

    content = post.get(
        "content",
        []
    )

    if not isinstance(content, list):
        return ""

    pieces = []

    for block in content:

        if not isinstance(block, dict):
            continue

        text = block.get(
            "text",
            ""
        )

        if text:

            text = clean_text(
                text
            )

            if text:
                pieces.append(text)

    return " ".join(pieces)


# ============================================================
# GET TITLE
# ============================================================

def get_post_title(post):

    content = post.get(
        "content",
        []
    )

    # First look for Tumblr heading blocks.
    if isinstance(content, list):

        for block in content:

            if not isinstance(block, dict):
                continue

            subtype = block.get(
                "subtype",
                ""
            )

            if subtype in (
                "heading1",
                "heading2",
                "heading3"
            ):

                text = clean_text(
                    block.get(
                        "text",
                        ""
                    )
                )

                if text:
                    return text[:200]

    # Tumblr's summary is usually a good fallback.
    summary = clean_text(
        post.get(
            "summary",
            ""
        )
    )

    if summary:
        return summary[:200]

    # Try the first text block.
    if isinstance(content, list):

        for block in content:

            if not isinstance(block, dict):
                continue

            if block.get("type") == "text":

                text = clean_text(
                    block.get(
                        "text",
                        ""
                    )
                )

                if text:
                    return text[:200]

    # Last fallback: Tumblr slug.
    slug = clean_text(
        post.get(
            "slug",
            ""
        )
    )

    if slug:

        return slug.replace(
            "-",
            " "
        )[:200]

    return "Tumblr post"


# ============================================================
# GET SHORT EXCERPT
# ============================================================

def get_post_excerpt(post):

    text = get_post_text(
        post
    )

    if not text:
        return ""

    # Keep RSS descriptions reasonably short.
    if len(text) > 400:
        text = text[:400].rstrip() + "..."

    return text


# ============================================================
# EXTRACT TUMBLR INITIAL JSON
# ============================================================

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

        return json.loads(
            script.string
        )

    except Exception as e:

        print(
            f"Could not parse initial JSON: {e}"
        )

        return None


# ============================================================
# SEARCH TUMBLR
# ============================================================

def search_tumblr(query):

    url = (
        "https://www.tumblr.com/search/"
        + quote(query)
    )

    print()
    print("=" * 50)
    print(
        f"Searching: {query}"
    )
    print(
        f"URL: {url}"
    )

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

        # Save the latest Tumblr response
        # for troubleshooting.
        with open(
            "tumblr_debug.html",
            "w",
            encoding="utf-8"
        ) as f:

            f.write(
                response.text
            )

        if response.status_code != 200:

            print(
                "Search request failed."
            )

            return []

        state = extract_initial_state(
            response.text
        )

        if not state:
            return []

        raw_posts = find_posts(
            state
        )

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

            # Remove query strings.
            post_url = post_url.split(
                "?"
            )[0]

            if post_url in seen:
                continue

            seen.add(
                post_url
            )

            results.append({
                "url": post_url,

                "title": get_post_title(
                    post
                ),

                "excerpt": get_post_excerpt(
                    post
                ),

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


# ============================================================
# MERGE OLD + NEW POSTS
# ============================================================

def merge_posts(existing, new_posts):

    posts_by_url = {}

    # IMPORTANT:
    # Start with ALL existing posts.
    # This prevents the database from being
    # replaced by only the newest search results.

    for post in existing:

        url = post.get(
            "url"
        )

        if url:
            posts_by_url[url] = post

    new_count = 0

    for post in new_posts:

        url = post.get(
            "url"
        )

        if not url:
            continue

        if url not in posts_by_url:

            post["added"] = datetime.now(
                timezone.utc
            ).isoformat()

            posts_by_url[url] = post

            new_count += 1

        else:

            existing_post = posts_by_url[
                url
            ]

            # Update title if the new version
            # has a useful one.
            new_title = post.get(
                "title",
                ""
            )

            if (
                new_title
                and new_title != "Tumblr post"
            ):

                existing_post["title"] = (
                    new_title
                )

            # Update excerpt if available.
            new_excerpt = post.get(
                "excerpt",
                ""
            )

            if new_excerpt:

                existing_post[
                    "excerpt"
                ] = new_excerpt

    posts = list(
        posts_by_url.values()
    )

    # Newest first.
    posts.sort(
        key=lambda x: (
            x.get(
                "timestamp",
                0
            ),
            x.get(
                "added",
                ""
            )
        ),
        reverse=True
    )

    print(
        f"Existing posts preserved: "
        f"{len(existing)}"
    )

    print(
        f"New posts added: "
        f"{new_count}"
    )

    print(
        f"Total after merge: "
        f"{len(posts)}"
    )

    return posts[:MAX_POSTS]


# ============================================================
# CREATE RSS XML
# ============================================================

def make_rss(posts):

    os.makedirs(
        SITE_DIR,
        exist_ok=True
    )

    # IMPORTANT:
    # Register the Atom namespace before creating
    # the XML document.
    #
    # Without this, ElementTree can produce:
    #
    #   <ns0:link>
    #
    # Instead we want:
    #
    #   <atom:link>
    #
    ET.register_namespace(
        "atom",
        "http://www.w3.org/2005/Atom"
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

    # Atom self-link.
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

    # ========================================================
    # RSS ITEMS
    # ========================================================

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
            {
                "isPermaLink": "true"
            }
        ).text = url

        description_parts = []

        blog = post.get(
            "blog",
            ""
        )

        if blog:

            description_parts.append(
                f"Blog: {blog}"
            )

        query = post.get(
            "query",
            ""
        )

        if query:

            description_parts.append(
                f"Found via: {query}"
            )

        excerpt = post.get(
            "excerpt",
            ""
        )

        if excerpt:

            description_parts.append(
                excerpt
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

    # ========================================================
    # WRITE XML
    # ========================================================

    tree = ET.ElementTree(
        rss
    )

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


# ============================================================
# CREATE HTML INDEX
# ============================================================

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

        blog = html.escape(
            post.get(
                "blog",
                ""
            )
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

        f.write(
            page
        )


# ============================================================
# MAIN
# ============================================================

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

        results = search_tumblr(
            query
        )

        all_new.extend(
            results
        )

    total_found = len(
        all_new
    )

    print()
    print("=" * 50)

    print(
        f"TOTAL RESULTS FOUND: "
        f"{total_found}"
    )

    print("=" * 50)

    # ========================================================
    # SAFETY CHECK
    # ========================================================

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

        # NEVER allow the database to shrink.
        if len(posts) < len(existing):

            print()
            print(
                "ERROR: Merged database is "
                "smaller than existing database."
            )

            print(
                "Refusing to overwrite posts.json."
            )

            posts = existing

        else:

            save_posts(
                posts
            )

    print()

    print(
        f"TOTAL POSTS IN DATABASE: "
        f"{len(posts)}"
    )

    make_rss(
        posts
    )

    make_index(
        posts
    )

    print()
    print(
        "===== COMPLETE ====="
    )


if __name__ == "__main__":
    main()
