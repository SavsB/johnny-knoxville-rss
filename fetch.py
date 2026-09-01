import os
import re
import json
import html
import time
import calendar
from datetime import datetime, timezone, date, timedelta
from email.utils import format_datetime
import xml.etree.ElementTree as ET

import requests
from bs4 import BeautifulSoup


# ============================================================
# CONFIGURATION
# ============================================================

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

MAX_POSTS = 1000

# Search backwards this many months.
HISTORY_MONTHS = 24

# Tumblr currently tends to return approximately 15 results
# for a search request.
TUMBLR_RESULT_LIMIT = 15

# We recursively split date ranges when Tumblr returns a full
# result set. Keeping this at 2 prevents excessive requests.
MAX_SPLIT_DEPTH = 2

REQUEST_TIMEOUT = 30

TUMBLR_SEARCH_URL = "https://www.tumblr.com/search/{}"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/139.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


# ============================================================
# RELEVANCE / QUALITY FILTERING
# ============================================================

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

# Search/index pages frequently leak into Tumblr's search JSON.
# These patterns are used only to reject NEW results before they
# are added to posts.json.
SEARCH_PAGE_PATTERNS = [
    r"\btumblr\s+search\b",
    r"\bsearch\s+results?\b",
    r"\bsearch\s+for\b",
    r"\bresults?\s+for\b",
]

# These are usually metadata/page titles rather than actual fic
# titles. We only reject them when the post also lacks meaningful
# post content.
GENERIC_PAGE_TITLE_PATTERNS = [
    r"^johnny knoxville fanfiction\s*[—-]\s*tumblr$",
    r"^johnny knoxville\s*[—-]\s*tumblr$",
    r"^johnny knoxville reader\s*[—-]\s*tumblr$",
    r"^johnny knoxville imagine\s*[—-]\s*tumblr$",
    r"^johnny knoxville fic\s*[—-]\s*tumblr$",
    r"^johnny knoxville x reader\s*[—-]\s*tumblr$",
    r"^johnny knoxville x oc\s*[—-]\s*tumblr$",
]


# ============================================================
# BASIC HELPERS
# ============================================================

def clean_text(value):
    if value is None:
        return ""

    if isinstance(value, (list, tuple)):
        value = " ".join(str(x) for x in value)

    value = str(value)

    value = html.unescape(value)

    try:
        value = BeautifulSoup(value, "html.parser").get_text(" ", strip=True)
    except Exception:
        pass

    value = re.sub(r"\s+", " ", value)

    return value.strip()


def normalize_for_matching(value):
    value = clean_text(value).lower()

    value = value.replace("_", " ")
    value = value.replace("-", " ")

    value = re.sub(r"\s+", " ", value)

    return value.strip()


def normalize_url(url):
    if not url:
        return ""

    url = str(url).strip()

    # Remove fragments.
    url = url.split("#", 1)[0]

    # Tumblr sometimes produces trailing slashes inconsistently.
    url = url.rstrip("/")

    return url


# ============================================================
# DATABASE
# ============================================================

def load_posts():
    if not os.path.exists(POSTS_FILE):
        return []

    try:
        with open(POSTS_FILE, "r", encoding="utf-8") as f:
            posts = json.load(f)
    except Exception as e:
        print(f"Could not read {POSTS_FILE}: {e}")
        return []

    if not isinstance(posts, list):
        print("posts.json did not contain a list. Starting empty.")
        return []

    original_count = len(posts)

    posts = deduplicate_posts(posts)

    removed = original_count - len(posts)

    if removed:
        print(f"Deduplicated {removed} duplicate URL record(s).")

    return posts


def save_posts(posts):
    with open(POSTS_FILE, "w", encoding="utf-8") as f:
        json.dump(posts, f, indent=2, ensure_ascii=False)


def load_search_state():
    if not os.path.exists(STATE_FILE):
        return {
            "historical_month_offset": 1
        }

    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            state = json.load(f)

        if not isinstance(state, dict):
            return {"historical_month_offset": 1}

        return state

    except Exception as e:
        print(f"Could not read {STATE_FILE}: {e}")
        return {"historical_month_offset": 1}


def save_search_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


# ============================================================
# TUMBLR INITIAL STATE PARSER
# ============================================================

def extract_initial_state(html_text):
    soup = BeautifulSoup(html_text, "html.parser")

    script = soup.find(
        "script",
        id="___INITIAL_STATE___"
    )

    if not script:
        return None

    raw = script.string or script.get_text()

    if not raw:
        return None

    try:
        return json.loads(raw)
    except Exception as e:
        print(f"Could not parse Tumblr initial state: {e}")
        return None


def find_posts(obj, results=None):
    """
    Recursively search Tumblr's initial JSON state for post objects.
    """

    if results is None:
        results = []

    if isinstance(obj, dict):

        if (
            obj.get("objectType") == "post"
            and obj.get("postUrl")
        ):
            results.append(obj)

        for value in obj.values():
            find_posts(value, results)

    elif isinstance(obj, list):

        for item in obj:
            find_posts(item, results)

    return results


# ============================================================
# POST CONTENT EXTRACTION
# ============================================================

def get_post_text(post):
    possible_fields = [
        "body",
        "content",
        "text",
        "caption",
        "description",
        "excerpt",
    ]

    parts = []

    for field in possible_fields:
        value = post.get(field)

        if isinstance(value, list):

            for item in value:

                if isinstance(item, dict):
                    for subfield in [
                        "text",
                        "caption",
                        "body",
                        "content",
                    ]:
                        if item.get(subfield):
                            parts.append(
                                clean_text(item.get(subfield))
                            )

                elif isinstance(item, str):
                    parts.append(clean_text(item))

        elif value:
            parts.append(clean_text(value))

    return clean_text(" ".join(parts))


def get_post_title(post):
    for field in [
        "title",
        "summary",
        "name",
    ]:
        value = post.get(field)

        if value:
            return clean_text(value)

    return ""


def get_post_excerpt(post):
    text = get_post_text(post)

    if len(text) <= 500:
        return text

    return text[:497] + "..."


def get_post_tags(post):
    tags = post.get("tags", [])

    if isinstance(tags, list):
        cleaned = []

        for tag in tags:

            if isinstance(tag, dict):
                value = (
                    tag.get("name")
                    or tag.get("tag")
                    or tag.get("text")
                )

            else:
                value = tag

            if value:
                cleaned.append(clean_text(value))

        return cleaned

    if isinstance(tags, str):
        return [clean_text(tags)]

    return []


def parse_timestamp(value):
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

    value = str(value).strip()

    if not value:
        return None

    # ISO format.
    try:
        normalized = value.replace("Z", "+00:00")

        dt = datetime.fromisoformat(normalized)

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        return dt.astimezone(timezone.utc)

    except Exception:
        pass

    # Common Tumblr format.
    formats = [
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%d %H:%M:%S%z",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
    ]

    for fmt in formats:

        try:
            dt = datetime.strptime(value, fmt)

            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)

            return dt.astimezone(timezone.utc)

        except Exception:
            continue

    return None


def get_post_datetime(post):
    possible_fields = [
        "timestamp",
        "published",
        "date",
        "createdAt",
        "publishedAt",
    ]

    for field in possible_fields:

        value = post.get(field)

        dt = parse_timestamp(value)

        if dt:
            return dt

    return None


# ============================================================
# QUALITY FILTERING
# ============================================================

def has_knoxville_name(text):
    normalized = normalize_for_matching(text)

    return (
        "johnny knoxville" in normalized
        or "johnnyknoxville" in normalized
        or "johnny-knoxville" in normalized
        or bool(re.search(r"\bknoxville\b", normalized))
    )


def contains_excluded_character(text):
    normalized = normalize_for_matching(text)

    for character in EXCLUDED_CHARACTERS:

        if character in normalized:
            return True

    return False


def has_reader_or_oc_terms(text):
    normalized = normalize_for_matching(text)

    patterns = [
        r"\bx\s*reader\b",
        r"\bxreader\b",
        r"\breader\s*x\b",
        r"\breader\b",
        r"\byou\b",
        r"\byour\b",
        r"\byou're\b",
        r"\byou are\b",
        r"\boc\b",
        r"\boriginal character\b",
        r"\bself insert\b",
        r"\bself-insert\b",
        r"\bimagine\b",
        r"\bheadcanon\b",
        r"\boneshot\b",
        r"\bone shot\b",
        r"\bdrabble\b",
        r"\bfanfiction\b",
        r"\bfic\b",
    ]

    return any(
        re.search(pattern, normalized)
        for pattern in patterns
    )


def has_fic_terms(text):
    normalized = normalize_for_matching(text)

    patterns = [
        r"\bfanfiction\b",
        r"\bfic\b",
        r"\bstory\b",
        r"\bchapter\b",
        r"\boneshot\b",
        r"\bone shot\b",
        r"\bdrabble\b",
        r"\bimagine\b",
        r"\bheadcanon\b",
        r"\bwriting\b",
        r"\breader\b",
        r"\bx\s*reader\b",
        r"\bx\s*oc\b",
        r"\boc\b",
        r"\bsmut\b",
        r"\bfluff\b",
        r"\bangst\b",
    ]

    return any(
        re.search(pattern, normalized)
        for pattern in patterns
    )


def looks_like_search_page(title, text, url):
    """
    Detect obvious Tumblr search/index pages.

    IMPORTANT:
    We only reject very strong cases here. A real Tumblr post
    whose title happens to contain "Tumblr" should not be
    discarded merely because of that word.
    """

    normalized_title = normalize_for_matching(title)
    normalized_text = normalize_for_matching(text)
    normalized_url = normalize_for_matching(url)

    for pattern in SEARCH_PAGE_PATTERNS:

        if re.search(pattern, normalized_title):
            return True

    # Search URLs should not normally be returned as postUrl,
    # but this protects against malformed results.
    if "/search/" in normalized_url:
        return True

    # Generic generated page title with no meaningful body.
    for pattern in GENERIC_PAGE_TITLE_PATTERNS:

        if re.search(pattern, normalized_title):

            if len(normalized_text) < 80:
                return True

    return False


def is_knoxville_related(
    title,
    excerpt,
    blog,
    tags,
    query,
    url="",
):
    combined = " ".join(
        [
            title or "",
            excerpt or "",
            blog or "",
            " ".join(tags or []),
            query or "",
        ]
    )

    normalized = normalize_for_matching(combined)

    if contains_excluded_character(normalized):
        return False

    # Primary Knoxville signal.
    if has_knoxville_name(normalized):
        return True

    # Blog name can occasionally contain Knoxville.
    if has_knoxville_name(blog or ""):
        return True

    return False


def is_good_new_post(
    title,
    excerpt,
    blog,
    tags,
    query,
    url,
):
    """
    Quality gate applied to NEW results only.

    Existing records are preserved even if they would not pass
    today's stricter filter.
    """

    combined = " ".join(
        [
            title or "",
            excerpt or "",
            blog or "",
            " ".join(tags or []),
            query or "",
        ]
    )

    normalized = normalize_for_matching(combined)

    # Must have a real Tumblr post URL.
    if "/post/" not in (url or ""):
        return False

    # Remove obvious non-Knoxville Johnny fandoms.
    if contains_excluded_character(normalized):
        return False

    # Must have Knoxville somewhere in the actual result
    # metadata/content.
    if not has_knoxville_name(normalized):
        return False

    # Do not allow obvious search/index pages into the DB.
    if looks_like_search_page(title, excerpt, url):
        return False

    # If the result has actual fic/reader/OC language, it's
    # strongly desirable.
    if has_reader_or_oc_terms(normalized):
        return True

    # Otherwise keep genuine Knoxville fic/story material.
    if has_fic_terms(normalized):
        return True

    # Finally, allow Knoxville posts that were returned by a
    # specifically focused Knoxville query. This prevents the
    # crawler from becoming too aggressive and losing useful
    # material.
    focused_query = normalize_for_matching(query)

    if "johnny knoxville" in focused_query:
        return True

    return False


# ============================================================
# CONVERT TUMBLR JSON OBJECT
# ============================================================

def convert_post(post, query):
    url = normalize_url(
        post.get("postUrl")
        or post.get("url")
        or post.get("canonicalUrl")
        or ""
    )

    if not url:
        return None

    title = get_post_title(post)

    text = get_post_text(post)

    excerpt = get_post_excerpt(post)

    blog = (
        post.get("blogName")
        or post.get("blog")
        or post.get("blogUuid")
        or ""
    )

    if isinstance(blog, dict):
        blog = (
            blog.get("name")
            or blog.get("title")
            or ""
        )

    blog = clean_text(blog)

    tags = get_post_tags(post)

    dt = get_post_datetime(post)

    if dt:
        timestamp = dt.isoformat()
    else:
        timestamp = ""

    return {
        "link": url,
        "title": title or "Johnny Knoxville Tumblr Post",
        "url": url,
        "excerpt": excerpt,
        "query": query,
        "timestamp": timestamp,
        "blog": blog,
        "tags": tags,
        "added": datetime.now(timezone.utc).isoformat(),
    }


# ============================================================
# TUMBLR SEARCH
# ============================================================

def search_tumblr_request(query):
    encoded_query = requests.utils.quote(query)

    url = TUMBLR_SEARCH_URL.format(encoded_query)

    print(f"Searching Tumblr: {query}")

    try:
        response = requests.get(
            url,
            headers=HEADERS,
            timeout=REQUEST_TIMEOUT,
        )

    except requests.RequestException as e:
        print(f"Request failed: {e}")
        return []

    print(f"HTTP status: {response.status_code}")

    if response.status_code != 200:
        return []

    state = extract_initial_state(response.text)

    if not state:
        print("No Tumblr initial state found.")
        return []

    raw_posts = find_posts(state)

    print(f"Raw Tumblr post objects found: {len(raw_posts)}")

    converted = []

    seen_urls = set()

    for raw_post in raw_posts:

        converted_post = convert_post(
            raw_post,
            query,
        )

        if not converted_post:
            continue

        url = converted_post["url"]

        if url in seen_urls:
            continue

        seen_urls.add(url)

        converted.append(converted_post)

    print(f"Unique raw posts: {len(converted)}")

    return converted


# ============================================================
# RECENT SEARCH
# ============================================================

def search_recent():
    print()
    print("=" * 60)
    print("RECENT SEARCHES")
    print("=" * 60)

    all_results = []

    for query in QUERIES:

        results = search_tumblr_request(query)

        relevant = []

        for post in results:

            if is_good_new_post(
                post.get("title", ""),
                post.get("excerpt", ""),
                post.get("blog", ""),
                post.get("tags", []),
                post.get("query", ""),
                post.get("url", ""),
            ):
                relevant.append(post)

        print(
            f"{query} -> "
            f"{len(results)} raw, "
            f"{len(relevant)} relevant"
        )

        all_results.extend(relevant)

        time.sleep(1)

    all_results = deduplicate_posts(all_results)

    print(
        f"Recent unique Knoxville results: "
        f"{len(all_results)}"
    )

    return all_results


# ============================================================
# DATE SLICING
# ============================================================

def search_date_range(
    base_query,
    start_date,
    end_date,
    depth=0,
):
    query = (
        f"{base_query} "
        f"since:{start_date.isoformat()} "
        f"before:{end_date.isoformat()}"
    )

    results = search_tumblr_request(query)

    relevant = []

    for post in results:

        if is_good_new_post(
            post.get("title", ""),
            post.get("excerpt", ""),
            post.get("blog", ""),
            post.get("tags", []),
            post.get("query", ""),
            post.get("url", ""),
        ):
            relevant.append(post)

    print(
        f"Range {start_date} -> {end_date}: "
        f"{len(results)} raw, "
        f"{len(relevant)} relevant"
    )

    # If Tumblr returned fewer than the apparent result cap,
    # we have probably exhausted this date range.
    if len(results) < TUMBLR_RESULT_LIMIT:
        return relevant

    # Prevent excessive recursive requests.
    if depth >= MAX_SPLIT_DEPTH:
        return relevant

    # Do not split tiny ranges forever.
    if (end_date - start_date).days <= 1:
        return relevant

    days = (end_date - start_date).days

    midpoint = start_date + timedelta(
        days=days // 2
    )

    print(
        f"Splitting saturated range at {midpoint}"
    )

    first_half = search_date_range(
        base_query,
        start_date,
        midpoint,
        depth + 1,
    )

    second_half = search_date_range(
        base_query,
        midpoint,
        end_date,
        depth + 1,
    )

    return deduplicate_posts(
        first_half + second_half
    )


# ============================================================
# DATE UTILITIES
# ============================================================

def add_months(year, month, amount):
    month_index = year * 12 + (month - 1)

    month_index += amount

    new_year = month_index // 12

    new_month = month_index % 12 + 1

    return new_year, new_month


def get_historical_month(offset):
    today = datetime.now(timezone.utc).date()

    year, month = add_months(
        today.year,
        today.month,
        -offset,
    )

    start = date(
        year,
        month,
        1,
    )

    last_day = calendar.monthrange(
        year,
        month,
    )[1]

    end = date(
        year,
        month,
        last_day,
    ) + timedelta(days=1)

    return start, end


def search_historical_month(offset):
    start_date, end_date = get_historical_month(offset)

    print()
    print("=" * 60)
    print(
        "HISTORICAL MONTH:",
        start_date,
        "->",
        end_date,
    )
    print("=" * 60)

    all_results = []

    for query in QUERIES:

        results = search_date_range(
            query,
            start_date,
            end_date,
        )

        all_results.extend(results)

        time.sleep(1)

    all_results = deduplicate_posts(all_results)

    print(
        f"Historical unique Knoxville results: "
        f"{len(all_results)}"
    )

    return all_results


# ============================================================
# DEDUPLICATION / MERGING
# ============================================================

def deduplicate_posts(posts):
    seen = set()

    result = []

    duplicate_count = 0

    for post in posts:

        url = normalize_url(
            post.get("url")
            or post.get("link")
            or ""
        )

        if not url:
            continue

        if url in seen:
            duplicate_count += 1
            continue

        seen.add(url)

        post["url"] = url
        post["link"] = url

        result.append(post)

    if duplicate_count:
        print(
            f"Deduplicated "
            f"{duplicate_count} duplicate URL records."
        )

    return result


def merge_posts(existing, new_posts):
    """
    Preserve every existing record.

    New posts are appended only when their URL does not
    already exist.
    """

    existing = deduplicate_posts(existing)

    new_posts = deduplicate_posts(new_posts)

    existing_urls = {
        normalize_url(
            post.get("url")
            or post.get("link")
            or ""
        )
        for post in existing
    }

    added = 0

    for post in new_posts:

        url = normalize_url(
            post.get("url")
            or post.get("link")
            or ""
        )

        if not url:
            continue

        if url in existing_urls:
            continue

        existing.append(post)

        existing_urls.add(url)

        added += 1

    return existing, added


# ============================================================
# RSS GENERATION
# ============================================================

def get_sort_datetime(post):
    dt = parse_timestamp(
        post.get("timestamp")
        or post.get("published")
        or post.get("date")
    )

    if dt:
        return dt

    return datetime.min.replace(
        tzinfo=timezone.utc
    )


def make_rss(posts):
    os.makedirs(SITE_DIR, exist_ok=True)

    # Newest first.
    posts = sorted(
        posts,
        key=get_sort_datetime,
        reverse=True,
    )

    # Feed maximum.
    posts = posts[:MAX_POSTS]

    ET.register_namespace(
        "atom",
        "http://www.w3.org/2005/Atom"
    )

    rss = ET.Element(
        "rss",
        {
            "version": "2.0",
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
        "Tumblr posts related to Johnny Knoxville "
        "fanfiction, reader inserts, original characters, "
        "imagines, fic, and related Jackass content."
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

        title = (
            post.get("title")
            or "Johnny Knoxville Tumblr Post"
        )

        url = (
            post.get("url")
            or post.get("link")
            or ""
        )

        excerpt = (
            post.get("excerpt")
            or ""
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

        if excerpt:
            ET.SubElement(
                item,
                "description"
            ).text = excerpt

        dt = get_sort_datetime(post)

        if dt != datetime.min.replace(
            tzinfo=timezone.utc
        ):
            ET.SubElement(
                item,
                "pubDate"
            ).text = format_datetime(dt)

    tree = ET.ElementTree(rss)

    tree.write(
        FEED_FILE,
        encoding="utf-8",
        xml_declaration=True,
    )

    print(
        f"RSS feed created: {FEED_FILE}"
    )


# ============================================================
# INDEX PAGE
# ============================================================

def make_index(posts):
    os.makedirs(SITE_DIR, exist_ok=True)

    sorted_posts = sorted(
        posts,
        key=get_sort_datetime,
        reverse=True,
    )

    feed_url = (
        "https://savsb.github.io/"
        "johnny-knoxville-rss/feed.xml"
    )

    lines = [
        "<!DOCTYPE html>",
        "<html lang=\"en\">",
        "<head>",
        "<meta charset=\"UTF-8\">",
        "<meta name=\"viewport\" "
        "content=\"width=device-width, initial-scale=1.0\">",
        "<title>Johnny Knoxville Tumblr RSS</title>",
        "<style>",
        "body{font-family:Arial,sans-serif;"
        "max-width:900px;margin:40px auto;padding:20px;"
        "line-height:1.6;}",
        "code{background:#eee;padding:3px 6px;"
        "border-radius:4px;}",
        "a{color:#0645ad;}",
        "</style>",
        "</head>",
        "<body>",
        "<h1>Johnny Knoxville Tumblr RSS</h1>",
        "<p>",
        "This page provides an RSS feed of Tumblr posts "
        "found by automated searches for Johnny Knoxville "
        "fanfiction, reader inserts, OC stories, imagines, "
        "and related material.",
        "</p>",
        "<p>",
        f"<strong>{len(sorted_posts)}</strong> "
        "posts currently stored.",
        "</p>",
        "<p>",
        f"<a href=\"{feed_url}\">"
        "Subscribe to the RSS feed"
        "</a>",
        "</p>",
        "<h2>Latest posts</h2>",
        "<ul>",
    ]

    for post in sorted_posts[:50]:

        title = html.escape(
            post.get("title")
            or "Untitled"
        )

        url = html.escape(
            post.get("url")
            or post.get("link")
            or ""
        )

        lines.append(
            f"<li><a href=\"{url}\">{title}</a></li>"
        )

    lines.extend([
        "</ul>",
        "</body>",
        "</html>",
    ])

    with open(
        INDEX_FILE,
        "w",
        encoding="utf-8"
    ) as f:
        f.write("\n".join(lines))

    print(
        f"Index created: {INDEX_FILE}"
    )


# ============================================================
# MAIN
# ============================================================

def main():
    print("=" * 60)
    print("JOHNNY KNOXVILLE TUMBLR RSS CRAWLER")
    print("=" * 60)

    existing = load_posts()

    print(
        f"Existing posts loaded: {len(existing)}"
    )

    # --------------------------------------------------------
    # Recent searches
    # --------------------------------------------------------

    recent_posts = search_recent()

    # --------------------------------------------------------
    # Historical month
    # --------------------------------------------------------

    state = load_search_state()

    try:
        historical_offset = int(
            state.get(
                "historical_month_offset",
                1
            )
        )
    except Exception:
        historical_offset = 1

    if historical_offset < 1:
        historical_offset = 1

    if historical_offset > HISTORY_MONTHS:
        historical_offset = 1

    historical_posts = search_historical_month(
        historical_offset
    )

    # --------------------------------------------------------
    # Combine results from this run
    # --------------------------------------------------------

    run_posts = deduplicate_posts(
        recent_posts + historical_posts
    )

    print()
    print(
        f"Unique posts found this run: "
        f"{len(run_posts)}"
    )

    # --------------------------------------------------------
    # Merge WITHOUT deleting existing records
    # --------------------------------------------------------

    existing, added = merge_posts(
        existing,
        run_posts,
    )

    # Safety deduplication.
    existing = deduplicate_posts(existing)

    # --------------------------------------------------------
    # Keep the database from growing forever.
    #
    # IMPORTANT:
    # We only trim if we exceed MAX_POSTS.
    # Newest posts are retained.
    # --------------------------------------------------------

    if len(existing) > MAX_POSTS:

        existing = sorted(
            existing,
            key=get_sort_datetime,
            reverse=True,
        )[:MAX_POSTS]

        print(
            f"Database exceeded {MAX_POSTS}; "
            f"trimmed to newest {MAX_POSTS} posts."
        )

    print()
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

    save_posts(existing)

    print(
        f"Saved {len(existing)} posts to "
        f"{POSTS_FILE}"
    )

    # --------------------------------------------------------
    # Advance historical search cursor.
    #
    # Once all 24 months have been visited, start over.
    # --------------------------------------------------------

    historical_offset += 1

    if historical_offset > HISTORY_MONTHS:
        historical_offset = 1

    state["historical_month_offset"] = historical_offset

    save_search_state(state)

    print(
        f"Historical month completed: "
        f"{historical_offset - 1 if historical_offset > 1 else HISTORY_MONTHS}"
    )

    print(
        f"Next historical month: "
        f"{historical_offset}"
    )

    # --------------------------------------------------------
    # Generate website files
    # --------------------------------------------------------

    make_rss(existing)

    make_index(existing)

    print()
    print("=" * 60)
    print("CRAWL COMPLETE")
    print("=" * 60)
    print(
        f"Final post count: {len(existing)}"
    )


if __name__ == "__main__":
    main()
```
