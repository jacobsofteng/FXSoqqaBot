"""
Forum Image Scraper — Download Hellcat/Ferro/FFM/aid images from investsocial.com
"""
from playwright.sync_api import sync_playwright
import os
import time
import re
import urllib.request
import json
from pathlib import Path

# === Config ===
BASE_URL = "https://investsocial.com/ru/"
LOGIN_URL = BASE_URL
USERNAME = "Josef1974"
PASSWORD = "Forex1974_25"

THREADS = [
    "https://investsocial.com/ru/forum/forum-treyderov/torgovye-strategii/47751-torgovlja-po-metodam-v-d-ganna",
    "https://investsocial.com/ru/forum/forum-treyderov/torgovye-strategii/2662-arhiv-torgovlya-po-metodam-v-d-ganna",
]

TARGET_USERS = {
    "Hellcat": "195893",
    "Ferro": "33217",
    "FFM": "306080",
    "aid": None,  # We'll match by username text
}

PRIORITY_POSTS = [
    "25726886", "25806408", "25929158", "25929173", "25933128", "28068873",
    "33567518", "33675518", "33972266",
    "25777573", "24993746", "24817606", "29395499", "25022619",
]

OUTPUT_DIR = Path("forum_images")
PROGRESS_FILE = OUTPUT_DIR / "_progress.json"


def load_progress():
    if PROGRESS_FILE.exists():
        return json.loads(PROGRESS_FILE.read_text(encoding="utf-8"))
    return {"downloaded": [], "pages_done": [], "last_thread": None, "last_page": 0}


def save_progress(progress):
    PROGRESS_FILE.write_text(json.dumps(progress, indent=2), encoding="utf-8")


def setup_dirs():
    for user in TARGET_USERS:
        (OUTPUT_DIR / user).mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "unknown").mkdir(parents=True, exist_ok=True)


def download_image(url, filepath):
    """Download an image URL to a local file."""
    try:
        if url.startswith("//"):
            url = "https:" + url
        elif url.startswith("/"):
            url = "https://investsocial.com" + url

        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = resp.read()
            if len(data) < 500:  # Skip tiny/broken images
                return False
            with open(filepath, "wb") as f:
                f.write(data)
            return True
    except Exception as e:
        print(f"  [FAIL] {url}: {e}")
        return False


def dismiss_popups(page):
    """Dismiss cookie consent and other popups."""
    selectors = [
        "button:has-text('Accept')",
        "button:has-text('Принять')",
        "button:has-text('OK')",
        "button:has-text('Agree')",
        "button:has-text('Согласен')",
        ".cookie-consent button",
        ".popup-close",
        "#cookie-banner button",
    ]
    for sel in selectors:
        try:
            el = page.query_selector(sel)
            if el and el.is_visible():
                el.click()
                time.sleep(0.5)
        except:
            pass


def login(page):
    """Log into investsocial.com."""
    print("[LOGIN] Navigating to investsocial.com...")
    page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=60000)
    time.sleep(3)
    dismiss_popups(page)

    # Try to find login link/button
    login_clicked = False
    for selector in [
        "a:has-text('Вход')",
        "a:has-text('Войти')",
        "a:has-text('Login')",
        "a:has-text('Sign in')",
        ".login-link",
        "#login-link",
        "a[href*='login']",
        "a[href*='auth']",
    ]:
        try:
            el = page.query_selector(selector)
            if el and el.is_visible():
                el.click()
                login_clicked = True
                print(f"  Clicked login via: {selector}")
                time.sleep(3)
                break
        except:
            continue

    if not login_clicked:
        print("  [WARN] Could not find login button, trying direct login URL...")
        # Try common login URLs
        for login_path in [
            "https://investsocial.com/ru/login",
            "https://investsocial.com/login",
            "https://investsocial.com/ru/forum/login",
        ]:
            try:
                page.goto(login_path, wait_until="domcontentloaded", timeout=15000)
                time.sleep(2)
                break
            except:
                continue

    dismiss_popups(page)

    # Fill login form
    filled = False
    for user_sel in ["input[name='username']", "input[name='login']", "input[name='email']",
                      "input[type='text']", "input[type='email']", "#username", "#login",
                      "input[name='vb_login_username']", "input[name='Login']"]:
        try:
            el = page.query_selector(user_sel)
            if el and el.is_visible():
                el.fill(USERNAME)
                filled = True
                print(f"  Filled username via: {user_sel}")
                break
        except:
            continue

    for pass_sel in ["input[name='password']", "input[type='password']", "#password",
                      "input[name='vb_login_password']"]:
        try:
            el = page.query_selector(pass_sel)
            if el and el.is_visible():
                el.fill(PASSWORD)
                print(f"  Filled password via: {pass_sel}")
                break
        except:
            continue

    if not filled:
        print("  [WARN] Could not find login fields. Page might need manual interaction.")
        print("  Waiting 30 seconds for manual login...")
        time.sleep(30)
        return

    # Submit
    for submit_sel in ["button[type='submit']", "input[type='submit']",
                        "button:has-text('Войти')", "button:has-text('Вход')",
                        "button:has-text('Login')", "button:has-text('Sign in')",
                        ".login-button", "#login-submit"]:
        try:
            el = page.query_selector(submit_sel)
            if el and el.is_visible():
                el.click()
                print(f"  Submitted via: {submit_sel}")
                time.sleep(5)
                break
        except:
            continue

    dismiss_popups(page)
    print("[LOGIN] Done. Checking if logged in...")
    time.sleep(2)


def identify_user(post_element):
    """Try to identify which target user wrote a post."""
    try:
        text = post_element.inner_text()
    except:
        return None, None

    # Check for user links or username text
    for username, uid in TARGET_USERS.items():
        if username.lower() in text.lower():
            return username, uid
        if uid:
            try:
                user_link = post_element.query_selector(f"a[href*='{uid}']")
                if user_link:
                    return username, uid
            except:
                pass

    return None, None


def get_post_id(post_element):
    """Extract post ID from a post element."""
    try:
        # Try various attributes
        for attr in ["id", "data-post-id", "data-id"]:
            val = post_element.get_attribute(attr)
            if val:
                # Extract numbers
                nums = re.findall(r'\d+', val)
                if nums:
                    return nums[0]

        # Try finding anchor/permalink
        for sel in ["a[id*='post']", "a[name*='post']", ".post-id", "[data-post]"]:
            el = post_element.query_selector(sel)
            if el:
                val = el.get_attribute("id") or el.get_attribute("name") or el.get_attribute("data-post") or ""
                nums = re.findall(r'\d+', val)
                if nums:
                    return nums[0]
    except:
        pass
    return None


def extract_images_from_post(post_element):
    """Get all meaningful image URLs from a post."""
    urls = []
    try:
        imgs = post_element.query_selector_all("img")
        for img in imgs:
            src = img.get_attribute("src") or img.get_attribute("data-src") or ""
            # Skip tiny icons, smilies, avatars
            if any(skip in src.lower() for skip in [
                "smil", "emoji", "avatar", "icon", "logo", "button",
                "spacer", "pixel", "blank", "clear", "1x1",
                "/images/misc/", "/images/icons/", "/images/buttons/",
            ]):
                continue
            if src and ("attach" in src.lower() or "upload" in src.lower() or
                       "image" in src.lower() or ".png" in src.lower() or
                       ".jpg" in src.lower() or ".jpeg" in src.lower() or
                       ".gif" in src.lower()):
                urls.append(src)
            elif src and not any(skip in src.lower() for skip in ["smil", "emoji", "avatar", "icon"]):
                # Include other images that look like content
                urls.append(src)
    except:
        pass

    # Also check for linked images (thumbnails that link to full-size)
    try:
        links = post_element.query_selector_all("a[href*='attach'], a[href*='image'], a[href*='upload']")
        for link in links:
            href = link.get_attribute("href") or ""
            if any(ext in href.lower() for ext in [".png", ".jpg", ".jpeg", ".gif", ".bmp"]):
                urls.append(href)
    except:
        pass

    return list(set(urls))  # Deduplicate


def scrape_thread_page(page, progress):
    """Scrape all target user posts from the current page."""
    downloaded_count = 0

    # Try various post container selectors
    post_selectors = [
        ".post", ".message", ".forum-post", ".post-container",
        "[id^='post_']", "[id^='post-']", ".postcontainer",
        "div[id*='post']", "li[id*='post']", "article",
        ".b-post", ".topic-post", ".ipsPost",
    ]

    posts = []
    for sel in post_selectors:
        posts = page.query_selector_all(sel)
        if len(posts) > 0:
            print(f"  Found {len(posts)} posts via selector: {sel}")
            break

    if not posts:
        print("  [WARN] No posts found on page. Trying broader search...")
        # Try to find any images on the page from target users
        all_imgs = page.query_selector_all("img")
        print(f"  Found {len(all_imgs)} total images on page")
        return 0

    for post in posts:
        username, uid = identify_user(post)
        if not username:
            continue

        post_id = get_post_id(post) or "unknown"
        images = extract_images_from_post(post)

        if not images:
            continue

        print(f"  [{username}] Post {post_id}: {len(images)} images")

        for i, img_url in enumerate(images):
            img_key = f"{username}_{post_id}_{i}"
            if img_key in progress["downloaded"]:
                continue

            # Determine extension
            ext = ".png"
            for e in [".jpg", ".jpeg", ".gif", ".bmp", ".png"]:
                if e in img_url.lower():
                    ext = e
                    break

            filepath = OUTPUT_DIR / username / f"{post_id}_{i+1}{ext}"
            if download_image(img_url, str(filepath)):
                progress["downloaded"].append(img_key)
                downloaded_count += 1
                print(f"    Saved: {filepath.name}")

            time.sleep(0.3)  # Be polite

    save_progress(progress)
    return downloaded_count


def try_priority_posts(page, progress):
    """Try to directly access priority posts."""
    print("\n[PRIORITY] Attempting direct access to priority posts...")

    url_patterns = [
        "https://investsocial.com/ru/forum/post/{post_id}",
        "https://investsocial.com/ru/forum/forum-treyderov/torgovye-strategii/47751-torgovlja-po-metodam-v-d-ganna?p={post_id}",
        "https://investsocial.com/ru/forum/forum-treyderov/torgovye-strategii/47751-torgovlja-po-metodam-v-d-ganna/page__findpost__{post_id}",
        "https://investsocial.com/ru/forum/showpost.php?p={post_id}",
    ]

    for post_id in PRIORITY_POSTS:
        if any(post_id in d for d in progress["downloaded"]):
            continue

        found = False
        for pattern in url_patterns:
            url = pattern.format(post_id=post_id)
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=15000)
                time.sleep(2)
                dismiss_popups(page)

                # Check if we got a valid page (not 404)
                if "404" in page.title() or "not found" in page.title().lower():
                    continue

                # Try to extract images from this page
                images = []
                all_imgs = page.query_selector_all("img")
                for img in all_imgs:
                    src = img.get_attribute("src") or img.get_attribute("data-src") or ""
                    if any(skip in src.lower() for skip in [
                        "smil", "emoji", "avatar", "icon", "logo", "button",
                        "spacer", "pixel", "blank", "1x1", "/misc/", "/icons/",
                    ]):
                        continue
                    if src and len(src) > 10:
                        images.append(src)

                if images:
                    print(f"  [HIT] Post {post_id}: {len(images)} images via {pattern.split('?')[0].split('/')[-1]}")
                    # Identify user from page content
                    page_text = page.inner_text("body")
                    user_dir = "unknown"
                    for username in TARGET_USERS:
                        if username.lower() in page_text.lower():
                            user_dir = username
                            break

                    for i, img_url in enumerate(images):
                        ext = ".png"
                        for e in [".jpg", ".jpeg", ".gif", ".bmp"]:
                            if e in img_url.lower():
                                ext = e
                                break
                        filepath = OUTPUT_DIR / user_dir / f"{post_id}_{i+1}{ext}"
                        if download_image(img_url, str(filepath)):
                            progress["downloaded"].append(f"{user_dir}_{post_id}_{i}")
                            print(f"    Saved: {filepath}")

                    save_progress(progress)
                    found = True
                    break
            except Exception as e:
                continue

        if not found:
            print(f"  [MISS] Post {post_id}: no working URL pattern")

        time.sleep(1)


def find_next_page(page):
    """Find and click the next page button, return True if successful."""
    for sel in [
        "a:has-text('Next')", "a:has-text('Следующая')", "a:has-text('»')",
        "a:has-text('>')", ".pagination-next a", "a.next",
        "a[rel='next']", ".pager-next a", "li.next a",
        "a:has-text('след')",
    ]:
        try:
            el = page.query_selector(sel)
            if el and el.is_visible():
                href = el.get_attribute("href")
                el.click()
                time.sleep(3)
                return True
        except:
            continue
    return False


def try_user_profile_posts(page, username, uid, progress):
    """Try to find user's posts via their profile."""
    if not uid:
        return

    profile_urls = [
        f"https://investsocial.com/ru/forum/user/{uid}-{username.lower()}/",
        f"https://investsocial.com/ru/forum/member.php?u={uid}",
        f"https://investsocial.com/ru/forum/members/{uid}/",
        f"https://investsocial.com/ru/forum/search?author={username}",
    ]

    print(f"\n[PROFILE] Trying to find {username}'s posts via profile...")
    for url in profile_urls:
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=15000)
            time.sleep(3)
            dismiss_popups(page)

            if "404" not in page.title() and "error" not in page.title().lower():
                print(f"  Profile page loaded: {url}")
                # Look for "posts" or "messages" tab
                for tab_sel in [
                    "a:has-text('Сообщения')", "a:has-text('Posts')",
                    "a:has-text('messages')", "a[href*='posts']",
                ]:
                    try:
                        tab = page.query_selector(tab_sel)
                        if tab and tab.is_visible():
                            tab.click()
                            time.sleep(3)
                            break
                    except:
                        continue

                # Scrape whatever we find
                scrape_thread_page(page, progress)
                return True
        except:
            continue

    print(f"  Could not find profile for {username}")
    return False


def main():
    setup_dirs()
    progress = load_progress()
    total_downloaded = len(progress["downloaded"])

    print(f"=== Forum Image Scraper ===")
    print(f"Previously downloaded: {total_downloaded} images")
    print(f"Output: {OUTPUT_DIR.absolute()}\n")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, slow_mo=500)
        context = browser.new_context(
            viewport={"width": 1400, "height": 900},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        )
        page = context.new_page()

        # Step 1: Login
        login(page)

        # Step 2: Try priority posts first
        try_priority_posts(page, progress)

        # Step 3: Try user profiles
        for username, uid in TARGET_USERS.items():
            if uid:
                try_user_profile_posts(page, username, uid, progress)

        # Step 4: Paginate through threads
        for thread_url in THREADS:
            print(f"\n[THREAD] {thread_url.split('/')[-1]}")

            page_num = 1
            # Resume from where we left off
            if thread_url == progress.get("last_thread"):
                page_num = progress.get("last_page", 1)
                if page_num > 1:
                    print(f"  Resuming from page {page_num}")

            # Navigate to thread
            start_url = thread_url if page_num <= 1 else f"{thread_url}/page/{page_num}"
            try:
                page.goto(start_url, wait_until="domcontentloaded", timeout=30000)
            except:
                page.goto(thread_url, wait_until="domcontentloaded", timeout=30000)
            time.sleep(3)
            dismiss_popups(page)

            empty_pages = 0
            max_pages = 500  # Safety limit

            while page_num <= max_pages:
                page_key = f"{thread_url}__p{page_num}"
                print(f"\n  --- Page {page_num} ---")

                if page_key in progress["pages_done"]:
                    print("  (already scraped, skipping)")
                    if not find_next_page(page):
                        break
                    page_num += 1
                    continue

                count = scrape_thread_page(page, progress)
                total_downloaded += count

                progress["pages_done"].append(page_key)
                progress["last_thread"] = thread_url
                progress["last_page"] = page_num
                save_progress(progress)

                print(f"  Page {page_num}: {count} new images (total: {total_downloaded})")

                if count == 0:
                    empty_pages += 1
                else:
                    empty_pages = 0

                # If 10 consecutive empty pages, this thread might be exhausted
                if empty_pages >= 10:
                    print("  10 consecutive empty pages, moving on...")
                    break

                # Try to go to next page
                if not find_next_page(page):
                    print("  No more pages in this thread.")
                    break

                page_num += 1
                time.sleep(1)  # Be polite

        print(f"\n=== DONE ===")
        print(f"Total images downloaded: {len(progress['downloaded'])}")

        # Summary per user
        for user in TARGET_USERS:
            user_dir = OUTPUT_DIR / user
            if user_dir.exists():
                count = len(list(user_dir.iterdir()))
                print(f"  {user}: {count} images")

        unknown_dir = OUTPUT_DIR / "unknown"
        if unknown_dir.exists():
            count = len(list(unknown_dir.iterdir()))
            if count:
                print(f"  unknown: {count} images")

        print("\nBrowser will stay open for 30 seconds for inspection...")
        time.sleep(30)
        browser.close()


if __name__ == "__main__":
    main()
