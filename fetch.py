import os
import re
import json
import html
import requests
import warnings

warnings.filterwarnings(
    "ignore",
    category=MarkupResemblesLocatorWarning
)

from bs4 import BeautifulSoup, MarkupResemblesLocatorWarning
from datetime import datetime, timezone, date, timedelta
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
STATE_FILE = "search_state.json"

SITE_DIR = "site"
FEED_FILE = os.path.join(SITE_DIR, "feed.xml")
INDEX_FILE = os.path.join(SITE_DIR, "index.html")

# Maximum number of posts retained in posts.json/feed.
MAX_POSTS = 1000

# How many months back the historical crawler cycles through.
HISTORY_MONTHS = 24

# Maximum number of times a busy date range will be split.
#
# Example:
# 1 month
#   -> 2 halves
#      -> 4 quarters
#
# This keeps the number of Tumblr requests under control.
MAX_SPLIT_DEPTH = 2

# Tumblr appears to cap web search results at 15.
TUMBLR_RESULT_LIMIT = 15

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/140.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


# ============================================================
# FILE HANDLING
# ============================================================

def load_posts():
    if not os.path.exists(POSTS_FILE):
        return []

    try:
        with open(POSTS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        if not isinstance(data, list):
            print("WARNING: posts.json did not contain a list.")
            return []

        return data

    except Exception as e:
        print(f"ERROR loading posts.json: {e}")
        return []


def save_posts(posts):
    with open(POSTS_FILE, "w", encoding="utf-8") as f:
        json.dump(posts, f, indent=2, ensure_ascii=False)


def load_search_state():
    """
    Keeps track of which historical month should be searched next.
    """

    if not os.path.exists(STATE_FILE):
        return {
            "next_month_offset": 1
        }

    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            state = json.load(f)

        offset = int(state.get("next_month_offset", 1))

        if offset < 1 or offset > HISTORY_MONTHS:
            offset = 1

        return {
            "next_month_offset": offset
        }

    except Exception as e:
        print(f"WARNING loading search state: {e}")

        return {
            "next_month_offset": 1
        }


def save_search_state(next_month_offset):
    if next_month_offset > HISTORY_MONTHS:
        next_month_offset = 1

    state = {
        "next_month_offset": next_month_offset
    }

    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


# ============================================================
# TEXT CLEANING
# ============================================================

def clean_text(value):
    if not value:
        return ""

    value = html.unescape(str(value))

    soup = BeautifulSoup(value, "html.parser")

    text = soup.get_text(" ", strip=True)

    text = re.sub(r"\s+", " ", text)

    return text.strip()


# ============================================================
# TUMBLR INITIAL STATE PARSER
# ============================================================

def extract_initial_state(soup):
    """
    Tumblr embeds search results inside:

        <script type="application/json" id="___INITIAL_STATE___">

    This function extracts that JSON.
    """

    script = soup.find(
        "script",
        {
            "type": "application/json",
            "id": "___INITIAL_STATE___"
        }
    )

    if not script:
        return None

    try:
        return json.loads(script.string or script.get_text())
    except Exception as e:
        print(f"WARNING: Could not parse Tumblr initial state: {e}")
        return None


def find_posts(obj, found=None):
    """
    Recursively searches Tumblr's JSON for post objects.
    """

    if found is None:
        found = []

    if isinstance(obj, dict):

        if (
            obj.get("objectType") == "post"
            and obj.get("postUrl")
        ):
            found.append(obj)

        for value in obj.values():
            find_posts(value, found)

    elif isinstance(obj, list):

        for item in obj:
            find_posts(item, found)

    return found


# ============================================================
# POST EXTRACTION
# ============================================================

def get_post_text(post):
    """
    Attempts to extract readable text from a Tumblr post.
    """

    candidates = []

    for key in [
        "summary",
        "caption",
        "body",
        "description",
    ]:
        value = post.get(key)

        if isinstance(value, str):
            candidates.append(value)

    blocks = post.get("content")

    if isinstance(blocks, list):

        for block in blocks:

            if not isinstance(block, dict):
                continue

            if block.get("type") == "text":

                text = block.get("text", "")

                if text:
                    candidates.append(text)

    for candidate in candidates:

        cleaned = clean_text(candidate)

        if cleaned:
            return cleaned

    return ""


def get_post_title(post):
    """
    Attempts to produce a useful title for the RSS item.
    """

    # Try headings first.
    blocks = post.get("content")

    if isinstance(blocks, list):

        for block in blocks:

            if not isinstance(block, dict):
                continue

            if block.get("type") in [
                "heading1",
                "heading2",
                "heading3",
            ]:

                text = clean_text(block.get("text", ""))

                if text:
                    return text

    # Tumblr summary.
    summary = clean_text(post.get("summary", ""))

    if summary:
        return summary[:120]

    # First text block.
    if isinstance(blocks, list):

        for block in blocks:

            if not isinstance(block, dict):
                continue

            if block.get("type") == "text":

                text = clean_text(block.get("text", ""))

                if text:
                    return text[:120]

    # Last resort: use the URL slug.
    url = post.get("postUrl", "")

    if url:

        slug = url.rstrip("/").split("/")[-1]

        if slug:
            return slug.replace("-", " ").replace("_", " ").title()

    return "Untitled Tumblr Post"


def get_post_excerpt(post):
    text = get_post_text(post)

    if not text:
        return "No text preview available."

    if len(text) > 400:
        return text[:397] + "..."

    return text


def convert_post(post, query):
    """
    Converts Tumblr's internal post object into our database format.
    """

    url = post.get("postUrl", "").strip()

    if not url:
        return None

    timestamp = post.get("timestamp", 0)

    try:
        timestamp = int(timestamp or 0)
    except (ValueError, TypeError):
        timestamp = 0

    blog_name = ""

    blog = post.get("blog")

    if isinstance(blog, dict):
        blog_name = (
            blog.get("name")
            or blog.get("title")
            or ""
        )

    if not blog_name:
        blog_name = post.get("blogName", "")

    tags = post.get("tags", [])

    if not isinstance(tags, list):
        tags = []

    tags = [
        clean_text(tag)
        for tag in tags
        if clean_text(tag)
    ]

    return {
        "url": url,
        "title": get_post_title(post),
        "excerpt": get_post_excerpt(post),
        "blog": blog_name,
        "timestamp": timestamp,
        "query": query,
        "tags": tags,
    }


# ============================================================
# TUMBLR SEARCH
# ============================================================

def search_tumblr_url(search_query):
    encoded = quote(search_query, safe="")

    return (
        f"https://www.tumblr.com/search/"
        f"{encoded}"
    )


def search_tumblr_request(search_query):
    """
    Performs one Tumblr search request.
    """

    url = search_tumblr_url(search_query)

    print(f"Searching: {search_query}")
    print(f"URL: {url}")

    try:

        response = requests.get(
            url,
            headers=HEADERS,
            timeout=30,
        )

        print(f"HTTP status: {response.status_code}")

        if response.status_code != 200:
            print(
                f"WARNING: Tumblr returned HTTP "
                f"{response.status_code}"
            )
            return []

        soup = BeautifulSoup(
            response.text,
            "html.parser"
        )

        state = extract_initial_state(soup)

        if not state:
            print("WARNING: Tumblr initial state not found.")
            return []

        raw_posts = find_posts(state)

        print(
            f"Raw post objects found: "
            f"{len(raw_posts)}"
        )

        results = []

        seen_urls = set()

        for raw_post in raw_posts:

            converted = convert_post(
                raw_post,
                search_query
            )

            if not converted:
                continue

            url = converted["url"]

            if url in seen_urls:
                continue

            seen_urls.add(url)

            results.append(converted)

        print(
            f"Usable unique posts: "
            f"{len(results)}"
        )

        return results

    except requests.RequestException as e:

        print(
            f"ERROR requesting Tumblr: {e}"
        )

        return []

    except Exception as e:

        print(
            f"ERROR processing Tumblr response: {e}"
        )

        return []


# ============================================================
# DATE HELPERS
# ============================================================

def add_months(original_date, months):
    """
    Adds/subtracts whole calendar months safely.
    """

    year = (
        original_date.year
        + (original_date.month - 1 + months) // 12
    )

    month = (
        (original_date.month - 1 + months) % 12
    ) + 1

    return date(
        year,
        month,
        1
    )


def get_historical_month(offset):
    """
    Returns the start and end dates for a historical month.

    offset 1 = previous month
    offset 2 = two months ago
    etc.
    """

    today = date.today()

    current_month_start = date(
        today.year,
        today.month,
        1
    )

    start = add_months(
        current_month_start,
        -offset
    )

    end = add_months(
        start,
        1
    )

    return start, end


# ============================================================
# DATE-SLICED SEARCH
# ============================================================

def search_date_range(
    base_query,
    start_date,
    end_date,
    depth=0
):
    """
    Searches a specific date range.

    If Tumblr returns the full 15-result limit,
    the range is split into smaller ranges.

    This is our replacement for /page/2 pagination.
    """

    date_query = (
        f"{base_query} "
        f"since:{start_date.isoformat()} "
        f"before:{end_date.isoformat()}"
    )

    results = search_tumblr_request(
        date_query
    )

    # Fewer than 15 results means we did not
    # hit Tumblr's apparent web-search limit.
    if len(results) < TUMBLR_RESULT_LIMIT:
        return results

    # We cannot subdivide indefinitely.
    if depth >= MAX_SPLIT_DEPTH:
        print(
            "Reached maximum date-splitting depth."
        )
        return results

    # A one-day range cannot be split any further.
    days = (end_date - start_date).days

    if days <= 1:
        print(
            "WARNING: This single-day range "
            "returned 15 results. Tumblr's web "
            "search may contain additional posts "
            "from this day that cannot be separated "
            "with date operators."
        )

        return results

    # Calculate the midpoint using timedelta.
    midpoint = start_date + timedelta(
        days=days // 2
    )

    # Safety check.
    if midpoint <= start_date:
        return results

    if midpoint >= end_date:
        return results

    print(
        f"Hit {TUMBLR_RESULT_LIMIT} results. "
        f"Splitting date range:"
    )

    print(
        f"  {start_date} -> {midpoint}"
    )

    print(
        f"  {midpoint} -> {end_date}"
    )

    first_half = search_date_range(
        base_query,
        start_date,
        midpoint,
        depth + 1
    )

    second_half = search_date_range(
        base_query,
        midpoint,
        end_date,
        depth + 1
    )

    combined = []

    seen_urls = set()

    for post in first_half + second_half:

        url = post.get(
            "url",
            ""
        ).strip()

        if not url:
            continue

        if url in seen_urls:
            continue

        seen_urls.add(url)

        combined.append(post)

    print(
        f"Combined split results: "
        f"{len(combined)}"
    )

    return combined


# ============================================================
# RECENT SEARCHES
# ============================================================

def search_recent():
    """
    Searches the normal Tumblr global search pages.

    These searches catch newly appearing posts.
    """

    all_results = []

    print()
    print("=" * 70)
    print("RECENT SEARCHES")
    print("=" * 70)

    for query in QUERIES:

        results = search_tumblr_request(
            query
        )

        all_results.extend(results)

    return all_results


# ============================================================
# HISTORICAL SEARCH
# ============================================================

def search_historical_month(month_offset):
    """
    Searches one historical month for every query.

    The month is remembered in search_state.json,
    so the next GitHub Actions run moves to the
    next month instead of repeating the same work.
    """

    start_date, end_date = get_historical_month(
        month_offset
    )

    print()
    print("=" * 70)
    print("HISTORICAL SEARCH")
    print("=" * 70)

    print(
        f"Month offset: {month_offset}"
    )

    print(
        f"Date range: "
        f"{start_date} -> {end_date}"
    )

    all_results = []

    for query in QUERIES:

        print()
        print(
            f"Historical query: {query}"
        )

        results = search_date_range(
            query,
            start_date,
            end_date
        )

        all_results.extend(results)

    return all_results


# ============================================================
# MERGING
# ============================================================

def merge_posts(existing, new_posts):

    merged = list(existing)

    existing_urls = set()

    for post in existing:

        url = post.get(
            "url",
            ""
        ).strip()

        if url:
            existing_urls.add(url)

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

            merged.append(post)

            existing_urls.add(url)

            new_count += 1

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
    print("=" * 70)
    print("MERGE RESULTS")
    print("=" * 70)

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

    if len(merged) > MAX_POSTS:

        print(
            f"Applying MAX_POSTS limit: "
            f"{MAX_POSTS}"
        )

        merged = merged[:MAX_POSTS]

    return merged


# ============================================================
# RSS GENERATION
# ============================================================

def make_rss(posts):

    os.makedirs(
        SITE_DIR,
        exist_ok=True
    )

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
    ).text = "Johnny Knoxville Tumblr Fanfiction"

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
        "Tumblr posts discovered through "
        "Johnny Knoxville and Jackass fanfiction "
        "searches."
    )

    ET.SubElement(
        channel,
        "language"
    ).text = "en-us"

    ET.SubElement(
        channel,
        "generator"
    ).text = "Custom Tumblr RSS scraper"

    # Atom self-link.
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

        ET.SubElement(
            item,
            "title"
        ).text = (
            post.get(
                "title",
                "Untitled Tumblr Post"
            )
        )

        ET.SubElement(
            item,
            "link"
        ).text = post.get(
            "url",
            ""
        )

        ET.SubElement(
            item,
            "guid"
        ).text = post.get(
            "url",
            ""
        )

        description_parts = []

        blog = post.get(
            "blog",
            ""
        )

        query = post.get(
            "query",
            ""
        )

        excerpt = post.get(
            "excerpt",
            ""
        )

        if blog:
            description_parts.append(
                f"<strong>Blog:</strong> "
                f"{html.escape(blog)}"
            )

        if query:
            description_parts.append(
                f"<strong>Found via:</strong> "
                f"{html.escape(query)}"
            )

        if excerpt:
            description_parts.append(
                html.escape(excerpt)
            )

        description = "<br><br>".join(
            description_parts
        )

        ET.SubElement(
            item,
            "description"
        ).text = description

        timestamp = post.get(
            "timestamp",
            0
        )

        try:

            timestamp = int(
                timestamp or 0
            )

        except (
            ValueError,
            TypeError
        ):

            timestamp = 0

        if timestamp:

            published = datetime.fromtimestamp(
                timestamp,
                tz=timezone.utc
            )

            ET.SubElement(
                item,
                "pubDate"
            ).text = published.strftime(
                "%a, %d %b %Y %H:%M:%S GMT"
            )

            ET.SubElement(
                item,
                "lastBuildDate"
            ).text = published.strftime(
                "%a, %d %b %Y %H:%M:%S GMT"
            )

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
        f"RSS feed created: {FEED_FILE}"
    )


# ============================================================
# GITHUB PAGES INDEX
# ============================================================

def make_index(posts):

    os.makedirs(
        SITE_DIR,
        exist_ok=True
    )

    html_content = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Johnny Knoxville Tumblr RSS</title>

<style>

body {
    font-family: Arial, sans-serif;
    max-width: 900px;
    margin: 40px auto;
    padding: 0 20px;
    line-height: 1.6;
}

code {
    background: #f1f1f1;
    padding: 3px 6px;
    border-radius: 4px;
}

.card {
    border: 1px solid #ddd;
    border-radius: 8px;
    padding: 15px;
    margin-bottom: 15px;
}

a {
    color: #0366d6;
}

</style>

</head>

<body>

<h1>Johnny Knoxville Tumblr RSS</h1>

<p>
This feed collects Tumblr posts discovered through
Johnny Knoxville and Jackass fanfiction searches.
</p>

<p>
<strong>Posts currently stored:</strong>
POST_COUNT
</p>

<h2>RSS Feed</h2>

<p>
<a href="feed.xml">
Subscribe to the RSS feed
</a>
</p>

<p>
RSS URL:
<br>
<code>
https://savsb.github.io/johnny-knoxville-rss/feed.xml
</code>
</p>

<h2>Search coverage</h2>

<p>
The scraper performs regular recent searches and
also searches historical date ranges to work around
Tumblr's web search result limit.
</p>

</body>
</html>
"""

    html_content = html_content.replace(
        "POST_COUNT",
        str(len(posts))
    )

    with open(
        INDEX_FILE,
        "w",
        encoding="utf-8"
    ) as f:

        f.write(html_content)

    print(
        f"Index created: {INDEX_FILE}"
    )


# ============================================================
# MAIN
# ============================================================

def main():

    print()
    print("=" * 70)
    print("TUMBLR RSS UPDATE")
    print("=" * 70)

    existing = load_posts()

    print(
        f"Existing database posts: "
        f"{len(existing)}"
    )

    # --------------------------------------------------------
    # Recent searches
    # --------------------------------------------------------

    recent_results = search_recent()

    # --------------------------------------------------------
    # Historical month
    # --------------------------------------------------------

    state = load_search_state()

    month_offset = state[
        "next_month_offset"
    ]

    historical_results = (
        search_historical_month(
            month_offset
        )
    )

    # --------------------------------------------------------
    # Combine results
    # --------------------------------------------------------

    all_results = (
        recent_results
        + historical_results
    )

    # --------------------------------------------------------
    # Deduplicate this run
    # --------------------------------------------------------

    unique_results = []

    seen_urls = set()

    for post in all_results:

        url = post.get(
            "url",
            ""
        ).strip()

        if not url:
            continue

        if url in seen_urls:
            continue

        seen_urls.add(url)

        unique_results.append(post)

    print()
    print(
        f"Total unique results found "
        f"this run: {len(unique_results)}"
    )

    # --------------------------------------------------------
    # Safety check
    # --------------------------------------------------------

    if len(unique_results) == 0:

        print()
        print(
            "WARNING: No Tumblr results were found."
        )

        print(
            "Existing database will be preserved."
        )

        merged = existing

    else:

        merged = merge_posts(
            existing,
            unique_results
        )

        # Never accidentally destroy existing data.
        if len(merged) < len(existing):

            print()
            print(
                "ERROR: Merge produced fewer posts "
                "than the existing database."
            )

            print(
                "Refusing to overwrite posts.json."
            )

            merged = existing

        else:

            save_posts(merged)

            print(
                "posts.json saved successfully."
            )

    # --------------------------------------------------------
    # Advance historical search cursor
    # --------------------------------------------------------

    next_offset = month_offset + 1

    if next_offset > HISTORY_MONTHS:
        next_offset = 1

    save_search_state(
        next_offset
    )

    print()
    print(
        f"Historical month completed: "
        f"{month_offset}"
    )

    print(
        f"Next historical month: "
        f"{next_offset}"
    )

    # --------------------------------------------------------
    # Generate RSS
    # --------------------------------------------------------

    make_rss(
        merged
    )

    make_index(
        merged
    )

    print()
    print("=" * 70)
    print("UPDATE COMPLETE")
    print("=" * 70)

    print(
        f"Final post count: {len(merged)}"
    )


if __name__ == "__main__":
    main()
