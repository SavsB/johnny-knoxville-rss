import os
import re
import json
import html
import warnings
import requests

from bs4 import BeautifulSoup, MarkupResemblesLocatorWarning
from datetime import date, timedelta, datetime, timezone
from urllib.parse import quote
from xml.etree import ElementTree as ET


# ============================================================
# CONFIGURATION
# ============================================================

# Searches specifically aimed at Johnny Knoxville fanfiction,
# reader inserts, imagines, OCs, and related writing.
QUERIES = [
    '"johnny knoxville" reader',
    '"johnny knoxville" imagine',
    '"johnny knoxville" fic',
    '"johnny knoxville" fanfiction',
    '"johnny knoxville" "x reader"',
    '"johnny knoxville" "x oc"',
    '"johnny knoxville" oneshot',
    '"johnny knoxville" "one shot"',
    '"johnny knoxville" writing',
    '"johnny knoxville" story',
    '"johnny knoxville" headcanon',
    '"johnny knoxville" drabble',
    '"johnny knoxville" smut',
]

POSTS_FILE = "posts.json"
STATE_FILE = "search_state.json"

SITE_DIR = "site"
FEED_FILE = os.path.join(SITE_DIR, "feed.xml")
INDEX_FILE = os.path.join(SITE_DIR, "index.html")

# Maximum number of posts retained in the RSS feed.
MAX_POSTS = 1000

# How many months backward the historical crawler should go.
HISTORY_MONTHS = 24

# Tumblr's global search currently appears to return about
# 15 results per search/range.
TUMBLR_RESULT_LIMIT = 15

# A date range that returns 15 results is split recursively.
# 2 means a maximum of 4 pieces per range.
MAX_SPLIT_DEPTH = 2

# Request timeout.
REQUEST_TIMEOUT = 30


# ============================================================
# WARNINGS
# ============================================================

warnings.filterwarnings(
    "ignore",
    category=MarkupResemblesLocatorWarning
)


# ============================================================
# HTTP SESSION
# ============================================================

SESSION = requests.Session()

SESSION.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/140.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
})


# ============================================================
# TEXT CLEANING
# ============================================================

def clean_text(value):
    """
    Convert arbitrary Tumblr content into clean plain text.
    """

    if value is None:
        return ""

    if isinstance(value, (dict, list)):
        try:
            value = json.dumps(value, ensure_ascii=False)
        except Exception:
            value = str(value)

    value = str(value)

    value = html.unescape(value)

    soup = BeautifulSoup(value, "html.parser")

    text = soup.get_text(" ", strip=True)

    text = re.sub(r"\s+", " ", text)

    return text.strip()


# ============================================================
# LOAD / SAVE POSTS
# ============================================================

def load_posts():
    """
    Load posts.json.

    The important part here is that old data is preserved.
    We also deduplicate it immediately.
    """

    if not os.path.exists(POSTS_FILE):
        return []

    try:
        with open(POSTS_FILE, "r", encoding="utf-8") as f:
            posts = json.load(f)

        if not isinstance(posts, list):
            print("WARNING: posts.json is not a list.")
            return []

        return deduplicate_posts(posts)

    except Exception as e:
        print(f"ERROR loading {POSTS_FILE}: {e}")
        return []


def save_posts(posts):
    """
    Save posts.json in a readable format.
    """

    with open(POSTS_FILE, "w", encoding="utf-8") as f:
        json.dump(
            posts,
            f,
            ensure_ascii=False,
            indent=2
        )

    print(f"posts.json saved successfully.")


# ============================================================
# SEARCH STATE
# ============================================================

def load_search_state():
    """
    Load the historical month cursor.

    Example:
        {"month_offset": 1}
    """

    if not os.path.exists(STATE_FILE):
        return {
            "month_offset": 1
        }

    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            state = json.load(f)

        if not isinstance(state, dict):
            return {
                "month_offset": 1
            }

        state.setdefault("month_offset", 1)

        return state

    except Exception as e:
        print(f"WARNING loading {STATE_FILE}: {e}")

        return {
            "month_offset": 1
        }


def save_search_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(
            state,
            f,
            ensure_ascii=False,
            indent=2
        )


# ============================================================
# TUMBLR INITIAL STATE
# ============================================================

def extract_initial_state(html_text):
    """
    Tumblr puts search results inside:

        <script type="application/json" id="___INITIAL_STATE___">

    Extract and decode that JSON.
    """

    soup = BeautifulSoup(html_text, "html.parser")

    script = soup.find(
        "script",
        {
            "id": "___INITIAL_STATE___",
            "type": "application/json"
        }
    )

    if not script:
        return None

    raw = script.string or script.get_text()

    if not raw:
        return None

    try:
        return json.loads(raw)

    except json.JSONDecodeError:
        try:
            return json.loads(
                html.unescape(raw)
            )
        except Exception:
            return None


# ============================================================
# FIND TUMBLR POSTS
# ============================================================

def find_posts(obj):
    """
    Recursively walk Tumblr's JSON and locate post objects.

    Tumblr's JSON structure changes periodically, so recursive
    searching is considerably safer than relying on one fixed path.
    """

    found = []

    if isinstance(obj, dict):

        if (
            obj.get("objectType") == "post"
            and obj.get("postUrl")
        ):
            found.append(obj)

        for value in obj.values():
            found.extend(find_posts(value))

    elif isinstance(obj, list):

        for value in obj:
            found.extend(find_posts(value))

    return found


# ============================================================
# POST EXTRACTION
# ============================================================

def get_post_text(post):
    """
    Extract useful text from Tumblr post JSON.
    """

    text_parts = []

    # Common Tumblr content fields.
    for key in (
        "summary",
        "body",
        "caption",
        "content",
        "trail",
    ):

        value = post.get(key)

        if value:
            if isinstance(value, list):

                for item in value:

                    if isinstance(item, dict):

                        for field in (
                            "text",
                            "content",
                            "title",
                            "summary",
                        ):

                            if item.get(field):
                                text_parts.append(
                                    clean_text(item.get(field))
                                )

                    else:
                        text_parts.append(
                            clean_text(item)
                        )

            elif isinstance(value, dict):

                text_parts.append(
                    clean_text(value)
                )

            else:

                text_parts.append(
                    clean_text(value)
                )

    return " ".join(
        x for x in text_parts
        if x
    ).strip()


def get_post_title(post):
    """
    Try to find the most useful title.
    """

    # Explicit title fields.
    for key in (
        "title",
        "summary",
    ):

        value = post.get(key)

        if value:
            value = clean_text(value)

            if value:
                return value[:300]

    # Look through content for headings.
    content = post.get("content")

    if isinstance(content, list):

        for item in content:

            if not isinstance(item, dict):
                continue

            item_type = item.get("type", "")

            if item_type in (
                "heading1",
                "heading2",
                "heading3",
            ):

                text = clean_text(
                    item.get("text")
                    or item.get("content")
                    or ""
                )

                if text:
                    return text[:300]

    # First useful text.
    text = get_post_text(post)

    if text:
        return text[:150]

    # Final fallback: URL slug.
    url = post.get("postUrl", "")

    if url:
        slug = url.rstrip("/").split("/")[-1]

        if slug:
            return slug[:200]

    return "Tumblr post"


def get_post_excerpt(post):
    """
    Get a short excerpt for the RSS feed.
    """

    text = get_post_text(post)

    if not text:
        text = get_post_title(post)

    return text[:400]


# ============================================================
# DATE HANDLING
# ============================================================

def parse_timestamp(value):
    """
    Convert Tumblr timestamps into timezone-aware UTC datetime.
    """

    if value is None:
        return None

    if isinstance(value, (int, float)):

        try:
            return datetime.fromtimestamp(
                value,
                tz=timezone.utc
            )
        except Exception:
            return None

    if isinstance(value, str):

        value = value.strip()

        if not value:
            return None

        # ISO timestamps.
        try:
            normalized = value.replace(
                "Z",
                "+00:00"
            )

            dt = datetime.fromisoformat(
                normalized
            )

            if dt.tzinfo is None:
                dt = dt.replace(
                    tzinfo=timezone.utc
                )

            return dt.astimezone(
                timezone.utc
            )

        except Exception:
            pass

        # Tumblr's older timestamp format.
        formats = [
            "%Y-%m-%d %H:%M:%S %Z",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d",
        ]

        for fmt in formats:

            try:
                dt = datetime.strptime(
                    value,
                    fmt
                )

                return dt.replace(
                    tzinfo=timezone.utc
                )

            except Exception:
                pass

    return None


def get_post_datetime(post):
    """
    Try several timestamp fields.
    """

    for key in (
        "timestamp",
        "published",
        "date",
        "createdAt",
        "updatedAt",
    ):

        dt = parse_timestamp(
            post.get(key)
        )

        if dt:
            return dt

    return None


# ============================================================
# JOHNNY KNOXVILLE RELEVANCE FILTER
# ============================================================

def normalize_for_matching(text):
    """
    Normalize text so things like:

        Johnny Knoxville
        johnny-knoxville
        johnny_knoxville

    can all be recognized.
    """

    text = clean_text(text).lower()

    text = text.replace(
        "_",
        " "
    )

    text = text.replace(
        "-",
        " "
    )

    text = re.sub(
        r"\s+",
        " ",
        text
    )

    return text.strip()


# These are obvious Johnny false positives that appeared during
# the broader searches.
EXCLUDED_CHARACTERS = [
    "johnny joestar",
    "johnny storm",
    "johnny silverhand",
    "johnny tightlips",
    "johnny bravo",
    "johnny cage",
    "johnny test",
    "johnny sins",
    "johnny lawrence",
    "johnny blaze",
    "johnny english",
    "johnny depp",
    "johnny cash",
]


def is_knoxville_related(post):
    """
    Decide whether a post is sufficiently connected to
    Johnny Knoxville to enter the RSS feed.

    We intentionally use a conservative approach:

    - "johnny knoxville" is strongest.
    - "knoxville" alone is accepted because many fanfics
      refer to him simply as Knoxville.
    - obvious unrelated Johnny characters are rejected.
    - Jackass alone is NOT enough, because Jackass has many
      cast members and produces unrelated fan content.
    """

    title = get_post_title(post)

    excerpt = get_post_excerpt(post)

    blog = post.get(
        "blog",
        ""
    )

    tags = post.get(
        "tags",
        []
    )

    if isinstance(tags, list):

        tags_text = " ".join(
            clean_text(x)
            for x in tags
        )

    else:

        tags_text = clean_text(tags)

    query = post.get(
        "query",
        ""
    )

    combined = " ".join([
        title,
        excerpt,
        blog,
        tags_text,
        query,
    ])

    normalized = normalize_for_matching(
        combined
    )

    # --------------------------------------------------------
    # Reject obvious unrelated Johnny characters first.
    # --------------------------------------------------------

    for excluded in EXCLUDED_CHARACTERS:

        if excluded in normalized:
            return False

    # --------------------------------------------------------
    # Strongest possible signal.
    # --------------------------------------------------------

    if "johnny knoxville" in normalized:
        return True

    # Common variations.
    if "johnnyknoxville" in normalized:
        return True

    if "johnny-knoxville" in normalized:
        return True

    # --------------------------------------------------------
    # Knoxville alone is a useful signal.
    # --------------------------------------------------------

    if re.search(
        r"\bknoxville\b",
        normalized
    ):
        return True

    # --------------------------------------------------------
    # Tumblr blogs sometimes use usernames that clearly
    # reference Knoxville. This is deliberately limited.
    # --------------------------------------------------------

    if "knoxville" in normalize_for_matching(blog):
        return True

    return False


# ============================================================
# CONVERT TUMBLR POST
# ============================================================

def convert_post(post, query):
    """
    Convert Tumblr's raw post object into our standardized
    posts.json format.
    """

    url = post.get(
        "postUrl"
    )

    if not url:
        return None

    timestamp = get_post_datetime(
        post
    )

    if timestamp:
        timestamp_text = timestamp.isoformat()

    else:
        timestamp_text = ""

    blog = ""

    blog_data = post.get(
        "blog"
    )

    if isinstance(blog_data, dict):

        blog = (
            blog_data.get("name")
            or blog_data.get("title")
            or ""
        )

    elif blog_data:

        blog = str(
            blog_data
        )

    # Preserve tags when available.
    tags = post.get(
        "tags",
        []
    )

    if not isinstance(tags, list):
        tags = []

    tags = [
        clean_text(tag)
        for tag in tags
        if clean_text(tag)
    ]

    return {
        "title": get_post_title(post),
        "url": url,
        "link": url,
        "excerpt": get_post_excerpt(post),
        "description": get_post_excerpt(post),
        "timestamp": timestamp_text,
        "published": timestamp_text,
        "blog": blog,
        "tags": tags,
        "query": query,
        "added": datetime.now(
            timezone.utc
        ).isoformat(),
    }


# ============================================================
# SEARCH TUMBLR
# ============================================================

def search_tumblr_request(search_query):
    """
    Perform one Tumblr search.
    """

    encoded = quote(
        search_query,
        safe=""
    )

    url = (
        "https://www.tumblr.com/search/"
        + encoded
    )

    print(
        f"    Searching: {search_query}"
    )

    try:

        response = SESSION.get(
            url,
            timeout=REQUEST_TIMEOUT
        )

    except requests.RequestException as e:

        print(
            f"    REQUEST ERROR: {e}"
        )

        return []

    print(
        f"    HTTP {response.status_code}"
    )

    if response.status_code != 200:

        return []

    state = extract_initial_state(
        response.text
    )

    if not state:

        print(
            "    WARNING: Tumblr initial state not found."
        )

        return []

    raw_posts = find_posts(
        state
    )

    print(
        f"    Raw posts found: {len(raw_posts)}"
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

        # ----------------------------------------------------
        # Strict Knoxville relevance filter.
        # ----------------------------------------------------

        if not is_knoxville_related(
            converted
        ):
            continue

        results.append(
            converted
        )

    print(
        f"    Knoxville-relevant: {len(results)}"
    )

    return results


# ============================================================
# RECENT SEARCHES
# ============================================================

def search_recent():
    """
    Search the current Tumblr search results for all targeted
    queries.
    """

    all_results = []

    print()
    print(
        "============================================================"
    )
    print(
        "RECENT SEARCHES"
    )
    print(
        "============================================================"
    )

    for query in QUERIES:

        results = search_tumblr_request(
            query
        )

        all_results.extend(
            results
        )

    return deduplicate_posts(
        all_results
    )


# ============================================================
# DATE RANGE SEARCHING
# ============================================================

def search_date_range(
    base_query,
    start_date,
    end_date,
    depth=0
):
    """
    Search a date range.

    If Tumblr returns its apparent maximum of 15 results,
    recursively divide the range so that older posts are
    not hidden behind the search limit.
    """

    query = (
        f"{base_query} "
        f"since:{start_date.isoformat()} "
        f"before:{end_date.isoformat()}"
    )

    indent = "    " * (
        depth + 1
    )

    print()
    print(
        f"{indent}DATE RANGE:"
    )
    print(
        f"{indent}{start_date} -> {end_date}"
    )
    print(
        f"{indent}Query: {query}"
    )

    results = search_tumblr_request(
        query
    )

    count = len(results)

    print(
        f"{indent}Accepted results: {count}"
    )

    # If fewer than Tumblr's apparent limit,
    # we probably got everything in this range.
    if count < TUMBLR_RESULT_LIMIT:

        return results

    # Do not split forever.
    if depth >= MAX_SPLIT_DEPTH:

        print(
            f"{indent}Maximum split depth reached."
        )

        return results

    # Cannot split a one-day range.
    if (
        end_date - start_date
    ).days <= 1:

        print(
            f"{indent}Range is too small to split further."
        )

        return results

    days = (
        end_date - start_date
    ).days

    midpoint = start_date + timedelta(
        days=days // 2
    )

    if midpoint <= start_date:
        return results

    if midpoint >= end_date:
        return results

    print(
        f"{indent}15-result limit reached; splitting range."
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

    return deduplicate_posts(
        first_half + second_half
    )


# ============================================================
# HISTORICAL MONTH HELPERS
# ============================================================

def add_months(
    source_date,
    months
):
    """
    Add/subtract whole calendar months safely.
    """

    month = (
        source_date.month
        - 1
        + months
    )

    year = (
        source_date.year
        + month // 12
    )

    month = (
        month % 12
        + 1
    )

    return date(
        year,
        month,
        1
    )


def get_historical_month(
    month_offset
):
    """
    Return the first and last boundary of a historical month.

    Offset 1 = previous calendar month.
    """

    today = date.today()

    first_day_current = date(
        today.year,
        today.month,
        1
    )

    start_date = add_months(
        first_day_current,
        -month_offset
    )

    end_date = add_months(
        first_day_current,
        -(month_offset - 1)
    )

    return (
        start_date,
        end_date
    )


# ============================================================
# HISTORICAL SEARCH
# ============================================================

def search_historical_month(
    month_offset
):
    """
    Search one historical month using every targeted query.

    Each query gets date slicing, so a busy month can be split
    into smaller ranges.
    """

    start_date, end_date = (
        get_historical_month(
            month_offset
        )
    )

    print()
    print(
        "============================================================"
    )
    print(
        "HISTORICAL MONTH"
    )
    print(
        "============================================================"
    )

    print(
        f"Month offset: {month_offset}"
    )

    print(
        f"Date range: {start_date} -> {end_date}"
    )

    all_results = []

    for base_query in QUERIES:

        print()
        print(
            f"BASE QUERY: {base_query}"
        )

        results = search_date_range(
            base_query,
            start_date,
            end_date,
            depth=0
        )

        all_results.extend(
            results
        )

        print(
            f"  Query total: {len(results)}"
        )

    return deduplicate_posts(
        all_results
    )


# ============================================================
# DEDUPLICATION
# ============================================================

def normalize_url(url):
    """
    Normalize Tumblr URLs enough to catch accidental duplicates.
    """

    if not url:
        return ""

    url = str(url).strip()

    # Remove trailing slash.
    url = url.rstrip("/")

    # Tumblr URLs are case-insensitive for the hostname.
    # Keep the path untouched.
    url = re.sub(
        r"^https?://",
        "https://",
        url,
        flags=re.IGNORECASE
    )

    return url


def deduplicate_posts(posts):
    """
    Deduplicate posts by URL.

    If duplicates have different metadata, merge the useful
    fields instead of blindly discarding one.
    """

    unique = {}

    duplicate_count = 0

    for post in posts:

        if not isinstance(post, dict):
            continue

        url = normalize_url(
            post.get("url")
            or post.get("link")
        )

        if not url:
            continue

        post["url"] = url

        if not post.get("link"):
            post["link"] = url

        if url not in unique:

            unique[url] = post

            continue

        duplicate_count += 1

        existing = unique[url]

        # Prefer non-empty values.
        for key, value in post.items():

            if (
                not existing.get(key)
                and value
            ):
                existing[key] = value

        # Merge tags.
        existing_tags = existing.get(
            "tags",
            []
        )

        new_tags = post.get(
            "tags",
            []
        )

        if not isinstance(
            existing_tags,
            list
        ):
            existing_tags = []

        if not isinstance(
            new_tags,
            list
        ):
            new_tags = []

        merged_tags = []

        for tag in (
            existing_tags
            + new_tags
        ):

            if tag not in merged_tags:
                merged_tags.append(tag)

        existing["tags"] = merged_tags

    if duplicate_count:

        print(
            f"Deduplicated {duplicate_count} duplicate URL record(s)."
        )

    return list(
        unique.values()
    )


# ============================================================
# MERGE
# ============================================================

def merge_posts(
    existing,
    new_posts
):
    """
    Preserve every unique existing post and add new posts.

    This also cleans up any duplicates already present in
    posts.json.
    """

    existing = deduplicate_posts(
        existing
    )

    new_posts = deduplicate_posts(
        new_posts
    )

    existing_urls = {
        normalize_url(
            post.get("url")
            or post.get("link")
        )
        for post in existing
    }

    added = 0

    for post in new_posts:

        url = normalize_url(
            post.get("url")
            or post.get("link")
        )

        if not url:
            continue

        if url in existing_urls:
            continue

        existing.append(
            post
        )

        existing_urls.add(
            url
        )

        added += 1

    # Sort newest first where dates exist.
    def sort_key(post):

        dt = get_post_datetime(
            post
        )

        if dt:
            return dt

        return datetime(
            1970,
            1,
            1,
            tzinfo=timezone.utc
        )

    existing.sort(
        key=sort_key,
        reverse=True
    )

    # Enforce maximum feed size.
    if len(existing) > MAX_POSTS:

        existing = existing[
            :MAX_POSTS
        ]

    print(
        f"Existing unique posts preserved: "
        f"{len(existing) - added}"
    )

    print(
        f"New posts added: {added}"
    )

    print(
        f"Total after merge: {len(existing)}"
    )

    return existing


# ============================================================
# RSS GENERATION
# ============================================================

def make_rss(posts):
    """
    Generate RSS 2.0 feed.
    """

    os.makedirs(
        SITE_DIR,
        exist_ok=True
    )

    # Register Atom namespace once.
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
        "Johnny Knoxville Tumblr Fanfiction"
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
        "reader inserts, fanfiction, imagines, OCs, "
        "and related writing."
    )

    ET.SubElement(
        channel,
        "language"
    ).text = "en"

    atom_link = ET.SubElement(
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

        item = ET.SubElement(
            channel,
            "item"
        )

        title = post.get(
            "title"
        ) or "Tumblr post"

        link = (
            post.get("url")
            or post.get("link")
            or ""
        )

        description = (
            post.get("excerpt")
            or post.get("description")
            or ""
        )

        ET.SubElement(
            item,
            "title"
        ).text = title

        ET.SubElement(
            item,
            "link"
        ).text = link

        ET.SubElement(
            item,
            "guid"
        ).text = link

        ET.SubElement(
            item,
            "description"
        ).text = description

        dt = get_post_datetime(
            post
        )

        if dt:

            ET.SubElement(
                item,
                "pubDate"
            ).text = dt.strftime(
                "%a, %d %b %Y %H:%M:%S GMT"
            )

    tree = ET.ElementTree(
        rss
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
# INDEX PAGE
# ============================================================

def make_index(posts):
    """
    Generate a simple GitHub Pages landing page.
    """

    os.makedirs(
        SITE_DIR,
        exist_ok=True
    )

    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Johnny Knoxville Tumblr RSS</title>
<style>
body {{
    font-family: Arial, sans-serif;
    max-width: 800px;
    margin: 40px auto;
    padding: 0 20px;
    line-height: 1.6;
}}

code {{
    background: #eee;
    padding: 3px 6px;
    border-radius: 4px;
}}

a {{
    color: #0366d6;
}}
</style>
</head>

<body>

<h1>Johnny Knoxville Tumblr RSS</h1>

<p>
This feed collects Tumblr posts related to
Johnny Knoxville fanfiction, reader inserts,
imagines, OCs, and related writing.
</p>

<p>
<strong>Posts currently tracked:</strong>
{len(posts)}
</p>

<h2>RSS Feed</h2>

<p>
<a href="feed.xml">
Open the RSS feed
</a>
</p>

<h2>Feed URL</h2>

<p>
<code>
https://savsb.github.io/johnny-knoxville-rss/feed.xml
</code>
</p>

</body>
</html>
"""

    with open(
        INDEX_FILE,
        "w",
        encoding="utf-8"
    ) as f:

        f.write(
            html_content
        )

    print(
        f"Index created: {INDEX_FILE}"
    )


# ============================================================
# MAIN
# ============================================================

def main():

    print()
    print(
        "============================================================"
    )
    print(
        "JOHNNY KNOXVILLE TUMBLR RSS CRAWLER"
    )
    print(
        "============================================================"
    )

    # --------------------------------------------------------
    # Load existing posts.
    # --------------------------------------------------------

    existing_posts = load_posts()

    print(
        f"Existing posts loaded: "
        f"{len(existing_posts)}"
    )

    # --------------------------------------------------------
    # Search current Tumblr results.
    # --------------------------------------------------------

    recent_results = search_recent()

    print()
    print(
        f"Recent unique Knoxville results: "
        f"{len(recent_results)}"
    )

    # --------------------------------------------------------
    # Search one historical month.
    # --------------------------------------------------------

    state = load_search_state()

    month_offset = int(
        state.get(
            "month_offset",
            1
        )
    )

    historical_results = (
        search_historical_month(
            month_offset
        )
    )

    print()
    print(
        f"Historical unique Knoxville results: "
        f"{len(historical_results)}"
    )

    # --------------------------------------------------------
    # Combine this run's results.
    # --------------------------------------------------------

    this_run = deduplicate_posts(
        recent_results
        + historical_results
    )

    print()
    print(
        "============================================================"
    )
    print(
        "RUN SUMMARY"
    )
    print(
        "============================================================"
    )

    print(
        f"Total unique results found this run: "
        f"{len(this_run)}"
    )

    # --------------------------------------------------------
    # Merge with existing database.
    # --------------------------------------------------------

    merged = merge_posts(
        existing_posts,
        this_run
    )

    # --------------------------------------------------------
    # Safety check.
    #
    # Never replace a healthy database with an empty/broken
    # scraper result.
    # --------------------------------------------------------

    if (
        len(this_run) == 0
        and len(existing_posts) > 0
    ):

        print()
        print(
            "WARNING: This run found zero results."
        )

        print(
            "Existing posts will be preserved."
        )

        merged = deduplicate_posts(
            existing_posts
        )

    # --------------------------------------------------------
    # Additional safety check against catastrophic loss.
    # --------------------------------------------------------

    if (
        len(existing_posts) >= 100
        and len(merged)
        < len(existing_posts) * 0.8
    ):

        print()
        print(
            "WARNING: Refusing to save because the "
            "merged database unexpectedly shrank."
        )

        print(
            f"Old count: {len(existing_posts)}"
        )

        print(
            f"New count: {len(merged)}"
        )

        merged = existing_posts

    # --------------------------------------------------------
    # Save posts.
    # --------------------------------------------------------

    save_posts(
        merged
    )

    # --------------------------------------------------------
    # Advance historical month cursor.
    #
    # This means each successful GitHub Actions run searches
    # the next month rather than repeatedly searching the same
    # historical month.
    # --------------------------------------------------------

    next_offset = (
        month_offset + 1
    )

    if next_offset > HISTORY_MONTHS:

        next_offset = 1

    state["month_offset"] = (
        next_offset
    )

    save_search_state(
        state
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
    # Generate website/feed.
    # --------------------------------------------------------

    make_rss(
        merged
    )

    make_index(
        merged
    )

    print()
    print(
        "============================================================"
    )

    print(
        f"FINAL POST COUNT: {len(merged)}"
    )

    print(
        "============================================================"
    )


if __name__ == "__main__":
    main()
