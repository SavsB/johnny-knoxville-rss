import json
import re
from collections import Counter
from datetime import datetime, timezone
from urllib.parse import urlparse


POSTS_FILE = "posts.json"

# How many examples to show from each category
EXAMPLES_PER_CATEGORY = 15


# ---------------------------------------------------------------------
# BASIC HELPERS
# ---------------------------------------------------------------------

def clean_text(value):
    if value is None:
        return ""

    if isinstance(value, list):
        return " ".join(clean_text(x) for x in value)

    if isinstance(value, dict):
        return " ".join(clean_text(v) for v in value.values())

    return str(value)


def normalize(text):
    text = clean_text(text).lower()

    # Normalize common separators
    text = text.replace("_", " ")
    text = text.replace("-", " ")
    text = text.replace("–", " ")
    text = text.replace("—", " ")

    # Collapse whitespace
    text = re.sub(r"\s+", " ", text)

    return text.strip()


def get_content(post):
    """
    Return the actual searchable content of a post.

    Query metadata is deliberately NOT included here when deciding
    whether a post itself is relevant. A query such as
    '"johnny knoxville" reader' cannot prove that the post itself
    is about Johnny Knoxville.
    """

    title = clean_text(post.get("title"))
    excerpt = clean_text(post.get("excerpt"))
    description = clean_text(post.get("description"))
    tags = clean_text(post.get("tags"))

    return normalize(
        " ".join([
            title,
            excerpt,
            description,
            tags,
        ])
    )


def get_all_metadata(post):
    """
    Everything available, including search metadata.
    Useful for diagnostics.
    """

    values = []

    for key in [
        "title",
        "excerpt",
        "description",
        "tags",
        "blog",
        "query",
    ]:
        values.append(clean_text(post.get(key)))

    return normalize(" ".join(values))


def get_url(post):
    return clean_text(post.get("url") or post.get("link"))


def get_blog(post):
    blog = clean_text(post.get("blog"))

    if blog:
        return blog

    url = get_url(post)

    if url:
        try:
            host = urlparse(url).netloc.lower()

            if host.startswith("www."):
                host = host[4:]

            if host.endswith(".tumblr.com"):
                return host[:-10]

            return host
        except Exception:
            pass

    return ""


def parse_date(post):
    value = (
        post.get("timestamp")
        or post.get("published")
        or post.get("date")
        or post.get("added")
    )

    if not value:
        return None

    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value, tz=timezone.utc)
        except Exception:
            return None

    value = str(value).strip()

    if not value:
        return None

    # ISO timestamps ending in Z
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"

    try:
        dt = datetime.fromisoformat(value)

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        return dt.astimezone(timezone.utc)

    except Exception:
        pass

    # Common fallback formats
    formats = [
        "%Y-%m-%d",
        "%Y-%m-%d %H:%M:%S",
    ]

    for fmt in formats:
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
        except Exception:
            pass

    return None


# ---------------------------------------------------------------------
# JOHNNY / JACKASS DETECTION
# ---------------------------------------------------------------------

EXCLUDED_JOHNNYS = [
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
    "johnny mnemonics",
    "johnny rico",
]


READER_PATTERNS = [
    r"\bx\s*reader\b",
    r"\bx!reader\b",
    r"\bfem!reader\b",
    r"\bgn!reader\b",
    r"\bmale!reader\b",
    r"\breader\b",
    r"\by/n\b",
    r"\by\\?n\b",
    r"\byour\b",
    r"\breader insert\b",
    r"\bself insert\b",
]


OC_PATTERNS = [
    r"\bx\s*oc\b",
    r"\bx!oc\b",
    r"\boc\b",
    r"\boriginal character\b",
    r"\boriginal female character\b",
    r"\boriginal male character\b",
]


FIC_PATTERNS = [
    r"\bfic\b",
    r"\bfics\b",
    r"\bfanfic\b",
    r"\bfanfiction\b",
    r"\bone shot\b",
    r"\boneshot\b",
    r"\bdrabble\b",
    r"\bchapter\b",
    r"\bmasterpost\b",
    r"\bmasterlist\b",
    r"\bimagine\b",
    r"\bheadcanon\b",
    r"\bheadcanons\b",
    r"\bwriting\b",
    r"\bstory\b",
    r"\bpart \d+\b",
]


JACKASS_PATTERNS = [
    r"\bjackass\b",
    r"\bjackass crew\b",
    r"\bjackass cast\b",
    r"\bjackass guys\b",
]


SEARCH_RESULT_PATTERNS = [
    r"\btumblr search result\b",
    r"\bsearch result\b",
    r"\bsearch results\b",
    r"\btumblr search\b",
]


def contains_any_pattern(text, patterns):
    return any(re.search(pattern, text) for pattern in patterns)


def has_reader(text):
    return contains_any_pattern(text, READER_PATTERNS)


def has_oc(text):
    return contains_any_pattern(text, OC_PATTERNS)


def has_fic_indicator(text):
    return contains_any_pattern(text, FIC_PATTERNS)


def has_jackass(text):
    return contains_any_pattern(text, JACKASS_PATTERNS)


def is_excluded_johnny(text):
    return any(name in text for name in EXCLUDED_JOHNNYS)


def has_johnny_knoxville(text):
    """
    Strongest identification.

    We require either:
      - johnny knoxville
      - johnny-knoxville
      - johnny_knoxville
      - Knoxville with Johnny nearby
    """

    if "johnny knoxville" in text:
        return True

    if "johnnyknoxville" in text:
        return True

    # Allow punctuation/separators between Johnny and Knoxville
    if re.search(r"\bjohnny[\s_\-–—]+knoxville\b", text):
        return True

    # "Knoxville" by itself is also a useful identifier,
    # but we treat it slightly differently elsewhere.
    return False


def has_knoxville(text):
    return bool(re.search(r"\bknoxville\b", text))


def has_standalone_johnny(text):
    """
    Detect Johnny without assuming which Johnny.
    """

    return bool(re.search(r"\bjohnny\b", text))


# ---------------------------------------------------------------------
# SEARCH-RESULT / GARBAGE DETECTION
# ---------------------------------------------------------------------

def is_search_result_page(post, content):
    title = normalize(post.get("title"))
    excerpt = normalize(post.get("excerpt"))
    description = normalize(post.get("description"))

    combined = " ".join([
        title,
        excerpt,
        description,
    ])

    # Extremely obvious Tumblr search-result pages
    if contains_any_pattern(combined, SEARCH_RESULT_PATTERNS):
        return True

    # Very common structure produced by Tumblr search-result posts
    if (
        "tumblr search result" in combined
        and "johnny knoxville" in combined
    ):
        return True

    return False


# ---------------------------------------------------------------------
# CLASSIFICATION
# ---------------------------------------------------------------------

CATEGORIES = [
    "JOHNNY KNOXVILLE + READER/OC",
    "JOHNNY KNOXVILLE FIC / IMAGINE",
    "JOHNNY KNOXVILLE - NON-FIC / OTHER",
    "JACKASS + READER/OC - JOHNNY UNCLEAR",
    "JACKASS FIC - JOHNNY UNCLEAR",
    "EXCLUDED / WRONG JOHNNY",
    "SEARCH RESULT / LOW-VALUE PAGE",
    "UNCERTAIN",
]


def classify(post):
    content = get_content(post)

    title = normalize(post.get("title"))
    excerpt = normalize(post.get("excerpt"))
    description = normalize(post.get("description"))
    tags = normalize(post.get("tags"))

    content_fields = " ".join([
        title,
        excerpt,
        description,
        tags,
    ])

    # -------------------------------------------------------------
    # 1. Search-result garbage gets removed first.
    # -------------------------------------------------------------

    if is_search_result_page(post, content_fields):
        return "SEARCH RESULT / LOW-VALUE PAGE"

    # -------------------------------------------------------------
    # 2. Explicitly wrong Johnnys.
    # -------------------------------------------------------------

    if is_excluded_johnny(content_fields):
        return "EXCLUDED / WRONG JOHNNY"

    # -------------------------------------------------------------
    # 3. Strong Johnny Knoxville identification.
    # -------------------------------------------------------------

    knoxville = has_johnny_knoxville(content)

    # "Knoxville" without Johnny can still be useful.
    if not knoxville and has_knoxville(content):
        knoxville = True

    # -------------------------------------------------------------
    # 4. Johnny Knoxville + Reader / OC
    # -------------------------------------------------------------

    if knoxville and (has_reader(content) or has_oc(content)):
        return "JOHNNY KNOXVILLE + READER/OC"

    # -------------------------------------------------------------
    # 5. Johnny Knoxville fanfiction / imagines.
    # -------------------------------------------------------------

    if knoxville and has_fic_indicator(content):
        return "JOHNNY KNOXVILLE FIC / IMAGINE"

    # -------------------------------------------------------------
    # 6. Johnny Knoxville but no obvious fic indicator.
    # -------------------------------------------------------------

    if knoxville:
        return "JOHNNY KNOXVILLE - NON-FIC / OTHER"

    # -------------------------------------------------------------
    # 7. Jackass + Reader/OC where Johnny isn't established.
    # -------------------------------------------------------------

    if has_jackass(content) and (has_reader(content) or has_oc(content)):
        return "JACKASS + READER/OC - JOHNNY UNCLEAR"

    # -------------------------------------------------------------
    # 8. Jackass fic without clear Johnny.
    # -------------------------------------------------------------

    if has_jackass(content) and has_fic_indicator(content):
        return "JACKASS FIC - JOHNNY UNCLEAR"

    # -------------------------------------------------------------
    # 9. Anything containing standalone Johnny but not Knoxville.
    # -------------------------------------------------------------

    if has_standalone_johnny(content):
        return "UNCERTAIN"

    # -------------------------------------------------------------
    # 10. Everything else.
    # -------------------------------------------------------------

    return "UNCERTAIN"


# ---------------------------------------------------------------------
# DISPLAY HELPERS
# ---------------------------------------------------------------------

def print_header(title):
    print()
    print("=" * 70)
    print(title)
    print("=" * 70)


def print_post(post):
    url = get_url(post)
    title = clean_text(post.get("title")) or "(no title)"
    blog = get_blog(post)

    print(f"URL:   {url}")
    print(f"Blog:  {blog}")
    print(f"Title: {title}")

    excerpt = clean_text(post.get("excerpt"))
    if excerpt:
        excerpt = excerpt.replace("\n", " ")
        if len(excerpt) > 500:
            excerpt = excerpt[:500] + "..."
        print(f"Text:  {excerpt}")

    query = clean_text(post.get("query"))
    if query:
        print(f"Query: {query}")

    print("-" * 50)


# ---------------------------------------------------------------------
# MAIN AUDIT
# ---------------------------------------------------------------------

def main():

    print("=" * 70)
    print("JOHNNY KNOXVILLE TUMBLR DATABASE AUDIT")
    print("=" * 70)

    # -------------------------------------------------------------
    # Load database
    # -------------------------------------------------------------

    try:
        with open(POSTS_FILE, "r", encoding="utf-8") as f:
            posts = json.load(f)
    except FileNotFoundError:
        print(f"ERROR: Could not find {POSTS_FILE}")
        return

    if not isinstance(posts, list):
        print("ERROR: posts.json does not contain a list.")
        return

    # -------------------------------------------------------------
    # Basic statistics
    # -------------------------------------------------------------

    urls = []

    for post in posts:
        url = get_url(post)

        if url:
            urls.append(url)

    unique_urls = set(urls)

    print_header("BASIC DATASET INFORMATION")

    print(f"Total records in posts.json: {len(posts)}")
    print(f"Records with a URL:           {len(urls)}")
    print(f"Unique URLs:                  {len(unique_urls)}")
    print(f"Duplicate URL records:       {len(urls) - len(unique_urls)}")
    print(f"Records without a URL:       {len(posts) - len(urls)}")

    duplicate_urls = [
        url
        for url, count in Counter(urls).items()
        if count > 1
    ]

    if duplicate_urls:
        print()
        print("DUPLICATE URLS:")

        counts = Counter(urls)

        for url in duplicate_urls:
            print(f"  {counts[url]}x {url}")
    else:
        print()
        print("No duplicate URLs found.")

    # -------------------------------------------------------------
    # Date coverage
    # -------------------------------------------------------------

    dated_posts = []

    for post in posts:
        dt = parse_date(post)

        if dt:
            dated_posts.append((dt, post))

    dated_posts.sort(key=lambda x: x[0])

    print_header("DATE COVERAGE")

    print(f"Posts with recognized dates: {len(dated_posts)}")
    print(f"Posts without recognized dates: {len(posts) - len(dated_posts)}")

    if dated_posts:
        oldest_dt, oldest_post = dated_posts[0]
        newest_dt, newest_post = dated_posts[-1]

        print()
        print(f"Oldest post: {oldest_dt}")
        print(f"  URL:   {get_url(oldest_post)}")
        print(f"  Title: {clean_text(oldest_post.get('title'))}")

        print()
        print(f"Newest post: {newest_dt}")
        print(f"  URL:   {get_url(newest_post)}")
        print(f"  Title: {clean_text(newest_post.get('title'))}")

    # -------------------------------------------------------------
    # By year
    # -------------------------------------------------------------

    year_counts = Counter()

    for dt, post in dated_posts:
        year_counts[dt.year] += 1

    print_header("POSTS BY YEAR")

    for year in sorted(year_counts):
        print(f"{year}: {year_counts[year]}")

    # -------------------------------------------------------------
    # By month
    # -------------------------------------------------------------

    month_counts = Counter()

    for dt, post in dated_posts:
        month_counts[dt.strftime("%Y-%m")] += 1

    print_header("POSTS BY MONTH")

    for month in sorted(month_counts):
        print(f"{month}: {month_counts[month]}")

    # -------------------------------------------------------------
    # Blog distribution
    # -------------------------------------------------------------

    blog_counts = Counter()

    for post in posts:
        blog = get_blog(post)

        if blog:
            blog_counts[blog] += 1

    print_header("BLOG / SOURCE DISTRIBUTION")

    print(f"Posts with identifiable blog/source: {sum(blog_counts.values())}")
    print(f"Unique blogs/sources: {len(blog_counts)}")

    print()
    print("Top 30 blogs/sources:")

    for blog, count in blog_counts.most_common(30):
        print(f"{count:4}  {blog}")

    # -------------------------------------------------------------
    # Classification
    # -------------------------------------------------------------

    categorized = {}

    for category in CATEGORIES:
        categorized[category] = []

    for post in posts:
        category = classify(post)
        categorized[category].append(post)

    print_header("PRECISE RELEVANCE ANALYSIS")

    for category in CATEGORIES:
        print(f"{len(categorized[category]):4}  {category}")

    # -------------------------------------------------------------
    # Percentage summary
    # -------------------------------------------------------------

    print_header("PERCENTAGE SUMMARY")

    total = len(posts)

    for category in CATEGORIES:
        count = len(categorized[category])

        if total:
            percentage = (count / total) * 100
        else:
            percentage = 0

        print(f"{count:4}  {percentage:6.2f}%  {category}")

    # -------------------------------------------------------------
    # Important category
    # -------------------------------------------------------------

    print_header("LIKELY MAIN FEED CONTENT")

    main_feed_count = len(
        categorized["JOHNNY KNOXVILLE + READER/OC"]
    )

    print(
        f"Likely Johnny Knoxville + Reader/OC posts: "
        f"{main_feed_count}"
    )

    print()
    print("These are the strongest candidates for your main RSS feed.")

    # -------------------------------------------------------------
    # Examples
    # -------------------------------------------------------------

    example_categories = [
        "JOHNNY KNOXVILLE + READER/OC",
        "JOHNNY KNOXVILLE FIC / IMAGINE",
        "JOHNNY KNOXVILLE - NON-FIC / OTHER",
        "JACKASS + READER/OC - JOHNNY UNCLEAR",
        "EXCLUDED / WRONG JOHNNY",
        "SEARCH RESULT / LOW-VALUE PAGE",
        "UNCERTAIN",
    ]

    for category in example_categories:

        posts_in_category = categorized[category]

        if not posts_in_category:
            continue

        print_header(
            f"EXAMPLES — {category}"
        )

        for post in posts_in_category[:EXAMPLES_PER_CATEGORY]:
            print_post(post)

    # -------------------------------------------------------------
    # Suspicious posts: Johnny appears, but Knoxville does not
    # -------------------------------------------------------------

    suspicious = []

    for post in posts:
        content = get_content(post)

        if (
            has_standalone_johnny(content)
            and not has_johnny_knoxville(content)
            and not has_knoxville(content)
            and not is_excluded_johnny(content)
        ):
            suspicious.append(post)

    print_header("SUSPICIOUS: 'JOHNNY' WITHOUT 'KNOXVILLE'")

    print(
        f"Posts containing standalone 'Johnny' without "
        f"an explicit Knoxville reference: {len(suspicious)}"
    )

    for post in suspicious[:EXAMPLES_PER_CATEGORY]:
        print_post(post)

    # -------------------------------------------------------------
    # Search metadata analysis
    # -------------------------------------------------------------

    query_counts = Counter()

    for post in posts:
        query = clean_text(post.get("query"))

        if query:
            query_counts[query] += 1

    print_header("SEARCH / QUERY METADATA")

    print(f"Records containing query metadata: {sum(query_counts.values())}")

    print()
    print("Most common stored queries:")

    for query, count in query_counts.most_common(30):
        print(f"{count:4}  {query}")

    # -------------------------------------------------------------
    # Field coverage
    # -------------------------------------------------------------

    fields = [
        "link",
        "title",
        "url",
        "excerpt",
        "query",
        "timestamp",
        "blog",
        "added",
        "tags",
        "published",
        "description",
    ]

    print_header("POST DATA STRUCTURE")

    for field in fields:
        count = sum(
            1
            for post in posts
            if post.get(field) not in (None, "", [], {})
        )

        print(
            f"{field:12}: {count}/{len(posts)}"
        )

    # -------------------------------------------------------------
    # Final recommendation
    # -------------------------------------------------------------

    print_header("RECOMMENDATION")

    strong = len(categorized["JOHNNY KNOXVILLE + READER/OC"])
    fic = len(categorized["JOHNNY KNOXVILLE FIC / IMAGINE"])
    other = len(categorized["JOHNNY KNOXVILLE - NON-FIC / OTHER"])
    wrong = len(categorized["EXCLUDED / WRONG JOHNNY"])
    garbage = len(categorized["SEARCH RESULT / LOW-VALUE PAGE"])
    jackass_reader = len(
        categorized["JACKASS + READER/OC - JOHNNY UNCLEAR"]
    )
    jackass_fic = len(
        categorized["JACKASS FIC - JOHNNY UNCLEAR"]
    )

    print(
        f"Strong Knoxville + Reader/OC: {strong}"
    )
    print(
        f"Knoxville fic/imagine:         {fic}"
    )
    print(
        f"Knoxville other:               {other}"
    )
    print(
        f"Wrong Johnny:                  {wrong}"
    )
    print(
        f"Search-result/low-value:       {garbage}"
    )
    print(
        f"Jackass + Reader/OC unclear:   {jackass_reader}"
    )
    print(
        f"Jackass fic unclear:           {jackass_fic}"
    )

    print()

    if strong >= 100:
        print(
            "RESULT: You have a substantial pool of likely "
            "Johnny Knoxville + Reader/OC material."
        )
    elif strong >= 50:
        print(
            "RESULT: You have a useful pool of likely "
            "Johnny Knoxville + Reader/OC material."
        )
    else:
        print(
            "RESULT: The main Knoxville + Reader/OC pool is "
            "still relatively small."
        )

    print()
    print(
        "NEXT STEP: Review the examples above before increasing "
        "MAX_SPLIT_DEPTH."
    )

    print()
    print("Audit complete.")
    print()
    print(
        "This script did NOT modify posts.json, site/feed.xml, "
        "or site/index.html."
    )


if __name__ == "__main__":
    main()
