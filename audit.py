import json
import os
import re
from collections import Counter
from datetime import datetime
from urllib.parse import urlparse


POSTS_FILE = "posts.json"


def load_posts():
    if not os.path.exists(POSTS_FILE):
        print(f"ERROR: {POSTS_FILE} was not found.")
        raise SystemExit(1)

    with open(POSTS_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, list):
        return data

    if isinstance(data, dict):
        # Handle common possible structures.
        for key in ("posts", "items", "results", "data"):
            if isinstance(data.get(key), list):
                return data[key]

    print("ERROR: Could not find a list of posts in posts.json.")
    raise SystemExit(1)


def get_url(post):
    for key in ("url", "postUrl", "link"):
        value = post.get(key)
        if value:
            return str(value)

    return ""


def get_text(post):
    parts = []

    for key in (
        "title",
        "summary",
        "description",
        "excerpt",
        "text",
        "body",
        "content",
        "caption",
    ):
        value = post.get(key)

        if isinstance(value, str):
            parts.append(value)

        elif isinstance(value, list):
            for item in value:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict):
                    for subkey in ("text", "content", "value"):
                        subvalue = item.get(subkey)
                        if isinstance(subvalue, str):
                            parts.append(subvalue)

    return " ".join(parts)


def get_title(post):
    for key in ("title", "name"):
        value = post.get(key)

        if isinstance(value, str) and value.strip():
            return value.strip()

    return ""


def get_date(post):
    for key in (
        "date",
        "published",
        "published_at",
        "timestamp",
        "datePublished",
        "postDate",
    ):
        value = post.get(key)

        if value is None:
            continue

        # Unix timestamp
        if isinstance(value, (int, float)):
            try:
                return datetime.fromtimestamp(value)
            except Exception:
                pass

        if isinstance(value, str):
            value = value.strip()

            # ISO date/time
            try:
                cleaned = value.replace("Z", "+00:00")
                return datetime.fromisoformat(cleaned)
            except Exception:
                pass

            # Common Tumblr date format
            for fmt in (
                "%Y-%m-%d",
                "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%dT%H:%M:%S.%f",
            ):
                try:
                    return datetime.strptime(value, fmt)
                except Exception:
                    pass

    return None


def get_blog(post):
    for key in (
        "blog",
        "blogName",
        "blog_name",
        "username",
        "author",
        "source",
    ):
        value = post.get(key)

        if isinstance(value, str) and value.strip():
            return value.strip()

        if isinstance(value, dict):
            for subkey in ("name", "title", "username", "url"):
                subvalue = value.get(subkey)
                if isinstance(subvalue, str) and subvalue.strip():
                    return subvalue.strip()

    url = get_url(post)

    if url:
        try:
            hostname = urlparse(url).hostname
            if hostname:
                hostname = hostname.lower()

                if hostname.endswith(".tumblr.com"):
                    return hostname.split(".")[0]
        except Exception:
            pass

    return ""


def normalize_url(url):
    url = url.strip()

    # Remove trailing slash.
    url = url.rstrip("/")

    return url.lower()


def classify_post(post):
    """
    Very rough relevance classification.

    This is intentionally conservative:
    - Strongly relevant:
      Johnny + reader/x reader
      Johnny + fic/fanfiction/imagine/oneshot/etc.
    - Possibly relevant:
      Johnny/Jackass + story/writing/etc.
    - Weak/uncertain:
      only Johnny or only Jackass
    - Unlikely:
      neither.
    """

    text = get_text(post).lower()

    # Normalize punctuation.
    normalized = re.sub(r"[^a-z0-9+#]+", " ", text)
    normalized = re.sub(r"\s+", " ", normalized).strip()

    johnny_terms = [
        "johnny knoxville",
        "johnny",
    ]

    jackass_terms = [
        "jackass",
    ]

    reader_terms = [
        "x reader",
        "xreader",
        "reader insert",
        "reader",
        "y/n",
        "your name",
    ]

    fic_terms = [
        "fanfiction",
        "fan fiction",
        "fic",
        "imagine",
        "oneshot",
        "one shot",
        "one-shot",
        "story",
        "writing",
        "chapter",
        "smut",
        "fluff",
        "headcanon",
        "headcanons",
    ]

    has_johnny = any(term in normalized for term in johnny_terms)
    has_jackass = any(term in normalized for term in jackass_terms)
    has_reader = any(term in normalized for term in reader_terms)
    has_fic = any(term in normalized for term in fic_terms)

    has_subject = has_johnny or has_jackass

    if has_johnny and has_reader:
        return "STRONG: Johnny + Reader"

    if has_johnny and has_fic:
        return "STRONG: Johnny + Fic"

    if has_jackass and has_reader:
        return "POSSIBLE: Jackass + Reader"

    if has_jackass and has_fic:
        return "POSSIBLE: Jackass + Fic"

    if has_subject and (has_reader or has_fic):
        return "POSSIBLE"

    if has_subject:
        return "WEAK: Subject only"

    return "UNLIKELY"


def print_section(title):
    print()
    print("=" * 70)
    print(title)
    print("=" * 70)


def main():
    posts = load_posts()

    print_section("BASIC DATASET INFORMATION")

    print(f"Total records in posts.json: {len(posts)}")

    # URLs
    urls = [get_url(post) for post in posts]
    nonempty_urls = [url for url in urls if url]

    normalized_urls = [normalize_url(url) for url in nonempty_urls]

    unique_urls = set(normalized_urls)

    print(f"Records with a URL:           {len(nonempty_urls)}")
    print(f"Unique URLs:                  {len(unique_urls)}")
    print(f"Duplicate URL records:       {len(nonempty_urls) - len(unique_urls)}")
    print(f"Records without a URL:       {len(posts) - len(nonempty_urls)}")

    # Duplicate URLs
    duplicate_counter = Counter(normalized_urls)

    duplicates = [
        (url, count)
        for url, count in duplicate_counter.items()
        if count > 1
    ]

    if duplicates:
        print()
        print("Duplicate URLs:")
        for url, count in sorted(
            duplicates,
            key=lambda x: (-x[1], x[0])
        )[:25]:
            print(f"  {count}x  {url}")
    else:
        print("\nNo duplicate URLs found.")

    # Dates
    print_section("DATE COVERAGE")

    dated_posts = []

    for post in posts:
        dt = get_date(post)

        if dt:
            dated_posts.append((dt, post))

    print(f"Posts with recognized dates: {len(dated_posts)}")
    print(f"Posts without recognized dates: {len(posts) - len(dated_posts)}")

    if dated_posts:
        dated_posts.sort(key=lambda x: x[0])

        oldest_dt, oldest_post = dated_posts[0]
        newest_dt, newest_post = dated_posts[-1]

        print()
        print(f"Oldest post: {oldest_dt}")
        print(f"  URL: {get_url(oldest_post)}")

        title = get_title(oldest_post)
        if title:
            print(f"  Title: {title}")

        print()
        print(f"Newest post: {newest_dt}")
        print(f"  URL: {get_url(newest_post)}")

        title = get_title(newest_post)
        if title:
            print(f"  Title: {title}")

    # Year/month distribution
    print_section("POSTS BY YEAR")

    year_counter = Counter()

    for dt, _ in dated_posts:
        year_counter[dt.year] += 1

    if year_counter:
        for year, count in sorted(year_counter.items()):
            print(f"{year}: {count}")

    print_section("POSTS BY MONTH")

    month_counter = Counter()

    for dt, _ in dated_posts:
        month_counter[dt.strftime("%Y-%m")] += 1

    if month_counter:
        for month, count in sorted(month_counter.items()):
            print(f"{month}: {count}")

    # Blogs
    print_section("BLOG / SOURCE DISTRIBUTION")

    blogs = []

    for post in posts:
        blog = get_blog(post)

        if blog:
            blogs.append(blog.lower())

    blog_counter = Counter(blogs)

    print(f"Posts with identifiable blog/source: {len(blogs)}")
    print(f"Unique blogs/sources: {len(blog_counter)}")

    if blog_counter:
        print()
        print("Top 30 blogs/sources:")

        for blog, count in blog_counter.most_common(30):
            print(f"{count:4}  {blog}")

    # Relevance
    print_section("ROUGH RELEVANCE ANALYSIS")

    classifications = []

    for post in posts:
        classification = classify_post(post)
        classifications.append(classification)

    class_counter = Counter(classifications)

    for category, count in class_counter.most_common():
        print(f"{count:4}  {category}")

    # Show examples
    for category in (
        "STRONG: Johnny + Reader",
        "STRONG: Johnny + Fic",
        "POSSIBLE: Jackass + Reader",
        "POSSIBLE: Jackass + Fic",
        "POSSIBLE",
        "WEAK: Subject only",
        "UNLIKELY",
    ):
        examples = [
            post
            for post in posts
            if classify_post(post) == category
        ]

        if not examples:
            continue

        print_section(f"EXAMPLES — {category}")

        for post in examples[:10]:
            print(f"URL: {get_url(post)}")

            title = get_title(post)
            if title:
                print(f"Title: {title}")

            text = get_text(post)
            text = re.sub(r"\s+", " ", text).strip()

            if len(text) > 300:
                text = text[:300] + "..."

            if text:
                print(f"Text: {text}")

            print("-" * 50)

    # Search/query metadata if present
    print_section("STORED SEARCH / QUERY METADATA")

    metadata_keys = Counter()

    for post in posts:
        for key in post.keys():
            key_lower = key.lower()

            if any(
                word in key_lower
                for word in ("query", "search", "source", "keyword")
            ):
                metadata_keys[key] += 1

    if metadata_keys:
        print("Possible search-related fields:")
        for key, count in metadata_keys.most_common():
            print(f"{key}: present in {count} records")

        print()
        print("Example values:")

        shown = 0

        for post in posts:
            for key in metadata_keys:
                if key in post:
                    print(f"{key}: {post[key]}")
                    shown += 1

                    if shown >= 20:
                        break

            if shown >= 20:
                break
    else:
        print("No obvious stored search/query metadata found.")

    # Field structure
    print_section("POST DATA STRUCTURE")

    all_keys = Counter()

    for post in posts:
        if isinstance(post, dict):
            for key in post.keys():
                all_keys[key] += 1

    print("Fields found across posts:")

    for key, count in all_keys.most_common():
        print(f"{key}: {count}/{len(posts)}")

    # Final summary
    print_section("AUDIT SUMMARY")

    duplicate_count = len(nonempty_urls) - len(unique_urls)

    strong_count = (
        class_counter.get("STRONG: Johnny + Reader", 0)
        + class_counter.get("STRONG: Johnny + Fic", 0)
    )

    possible_count = (
        class_counter.get("POSSIBLE: Jackass + Reader", 0)
        + class_counter.get("POSSIBLE: Jackass + Fic", 0)
        + class_counter.get("POSSIBLE", 0)
    )

    weak_count = class_counter.get("WEAK: Subject only", 0)
    unlikely_count = class_counter.get("UNLIKELY", 0)

    print(f"Total records:             {len(posts)}")
    print(f"Unique URLs:               {len(unique_urls)}")
    print(f"Duplicate URL records:    {duplicate_count}")
    print(f"Strongly relevant:         {strong_count}")
    print(f"Possibly relevant:         {possible_count}")
    print(f"Weak/uncertain:            {weak_count}")
    print(f"Unlikely:                  {unlikely_count}")

    if dated_posts:
        print(f"Date range:                {dated_posts[0][0]} -> {dated_posts[-1][0]}")

    print()
    print("Audit complete.")
    print("This script did NOT modify posts.json, site/feed.xml, or site/index.html.")


if __name__ == "__main__":
    main()
