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
    "johnny knoxville reader",
    "johnny knoxville imagine",
    "johnny knoxville fic",
    "johnny knoxville fanfiction",
    "johnny knoxville x oc",
    "johnny knoxville oneshot",
    "johnny knoxville one shot",
    "johnny knoxville writing",
    "johnny knoxville story",
    "jackass x reader",
    "jackass reader",
    "johnny x reader",
    "johnny x oc",
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

# Maximum number of posts kept in the database.
MAX_POSTS = 500

# Maximum number of Tumblr pages to try for EACH query.
#
# Page 1 = the normal search results.
# Page 2 = /page/2
# Page 3 = /page/3
# etc.
#
# Start conservatively. We can increase this later.
MAX_PAGES_PER_QUERY = 5

# How many pages returning only duplicates we tolerate
# before stopping.
#
# This protects us if Tumblr ignores /page/N and keeps
# returning the same 15 posts.
MAX_EMPTY_PAGES = 1


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/139.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,"
        "application/xml;q=0.9,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
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

    # Look for Tumblr heading blocks first.
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

    # Summary is the next best option.
    summary = clean_text(
        post.get(
            "summary",
            ""
        )
    )

    if summary:
        return summary[:200]

    # Try first text block.
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

    # Final fallback: slug.
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

    if len(text) > 400:

        text = (
            text[:400].rstrip()
            + "..."
        )

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
# CONVERT A TUMBLR POST INTO OUR DATABASE FORMAT
# ============================================================

def convert_post(
    post,
    query
):

    post_url = post.get(
        "postUrl",
        ""
    )

    if not post_url:
        return None

    post_url = post_url.split(
        "?"
    )[0]

    return {

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

        "tags": post.get(
            "tags",
            []
        ),
    }


# ============================================================
# SEARCH ONE TUMBLR PAGE
# ============================================================

def search_tumblr_page(
    query,
    page
):

    encoded_query = quote(
        query
    )

    if page == 1:

        url = (
            "https://www.tumblr.com/search/"
            + encoded_query
        )

    else:

        url = (
            "https://www.tumblr.com/search/"
            + encoded_query
            + f"/page/{page}"
        )

    print()
    print(
        f"Searching: {query} "
        f"(page {page})"
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

            converted = convert_post(
                post,
                query
            )

            if not converted:
                continue

            post_url = converted[
                "url"
            ]

            if post_url in seen:
                continue

            seen.add(
                post_url
            )

            results.append(
                converted
            )

        print(
            f"Found {len(results)} "
            f"unique posts on page {page}."
        )

        return results

    except Exception as e:

        print(
            f"Search error: {e}"
        )

        return []


# ============================================================
# SEARCH TUMBLR WITH PAGINATION
# ============================================================

def search_tumblr(query):

    all_results = []

    seen_urls = set()

    empty_pages = 0

    for page in range(
        1,
        MAX_PAGES_PER_QUERY + 1
    ):

        results = search_tumblr_page(
            query,
            page
        )

        # No results at all means we've reached
        # the end or Tumblr rejected the page.
        if not results:

            print(
                f"No results on page {page}."
            )

            break

        new_on_page = 0

        for post in results:

            url = post.get(
                "url",
                ""
            )

            if not url:
                continue

            if url in seen_urls:
                continue

            seen_urls.add(
                url
            )

            all_results.append(
                post
            )

            new_on_page += 1

        print(
            f"New posts from page {page}: "
            f"{new_on_page}"
        )

        # If Tumblr gave us a page but every post
        # was already seen, pagination probably isn't
        # advancing.
        if new_on_page == 0:

            empty_pages += 1

            print(
                "Page contained only "
                "duplicate posts."
            )

            if empty_pages >= MAX_EMPTY_PAGES:

                print(
                    "Stopping pagination because "
                    "Tumblr appears to be returning "
                    "the same results."
                )

                break

        else:

            empty_pages = 0

    print()
    print(
        f"TOTAL UNIQUE RESULTS FOR "
        f"'{query}': {len(all_results)}"
    )

    return all_results


# ============================================================
# MERGE OLD + NEW POSTS
# ============================================================

def merge_posts(
    existing,
    new_posts
):

    # Start with ALL existing posts.
    merged = list(
        existing
    )

    existing_urls = set()

    for post in existing:

        url = post.get(
            "url",
            ""
        ).strip()

        if url:

            existing_urls.add(
                url
            )

    new_count = 0

    for post in new_posts:

        url = post.get(
            "url",
            ""
        ).strip()

        if not url:
            continue

        if url not in existing_urls:

            post["added"] = (
                datetime.now(
                    timezone.utc
                ).isoformat()
            )

            merged.append(
                post
            )

            existing_urls.add(
                url
            )

            new_count += 1

    # Sort newest first.
    def sort_key(post):

        try:

            return int(
                post.get(
                    "timestamp",
                    0
                ) or 0
            )

        except (
            ValueError,
            TypeError
        ):

            return 0

    merged.sort(
        key=sort_key,
        reverse=True
    )

    print()
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
        f"{len(merged)}"
    )

    return merged[:MAX_POSTS]


# ============================================================
# CREATE RSS XML
# ============================================================

def make_rss(posts):

    os.makedirs(
        SITE_DIR,
        exist_ok=True
    )

    # Register Atom namespace.
    ET.register_namespace(
        "atom",
        "http://www.w3.org/2005/Atom"
    )

    rss = ET.Element(
        "rss",
        {
            "version": "2.0"
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

    # ========================================================
    # RUN EVERY SEARCH
    # ========================================================

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
