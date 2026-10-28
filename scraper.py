import os
import re
import json
import time
import requests
from bs4 import BeautifulSoup
import firebase_admin
from firebase_admin import credentials, db

# --- CONFIGURATION & DOMAIN ---
BASE_URL = "https://vegamovies.network"  # Active domain mirror structure
CATEGORY_PATHS = [
    "/hindi-dubbed/",
    "/dual-audio-movies/"
]
FIREBASE_DB_URL = "https://sijjmoviehub-default-rtdb.firebaseio.com" # Root or specific DB URL

def initialize_firebase():
    """Initializes Firebase Admin SDK securely using environment variables or fallback credential JSON."""
    if firebase_admin._apps:
        return
    
    # In GitHub Actions, store your Firebase Service Account JSON string in a secret named 'FIREBASE_SERVICE_ACCOUNT'
    cred_json = os.environ.get("FIREBASE_SERVICE_ACCOUNT")
    
    if cred_json:
        cred_dict = json.loads(cred_json)
        cred = credentials.Certificate(cred_dict)
        firebase_admin.initialize_app(cred, {
            'databaseURL': FIREBASE_DB_URL
        })
    else:
        # Fallback for local testing if file exists
        if os.path.exists("serviceAccountKey.json"):
            cred = credentials.Certificate("serviceAccountKey.json")
            firebase_admin.initialize_app(cred, {
                'databaseURL': FIREBASE_DB_URL
            })
        else:
            print("⚠️ Warning: No Firebase credentials found. Running in dry-run mode.")

def get_headers():
    return {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": BASE_URL
    }

def clean_movie_title(raw_title):
    """Cleans up WordPress blog noise, download tags, resolutions from titles."""
    # Removes tags like (2026) Dual Audio [Hindi-English] 1080p... but keeps the name & year
    title = re.sub(r'(Download|Full Movie|Vegamovies|Dual Audio|Hindi|English|WEB-DL|HDRip|BluRay|480p|720p|1080p).*', '', raw_title, flags=re.IGNORECASE)
    return title.strip(" -|[]()")

def extract_magnet_from_page(post_url):
    """Parses a movie's inner post page and extracts unique magnet links."""
    try:
        response = requests.get(post_url, headers=get_headers(), timeout=15)
        if response.status_code != 200:
            return []
        
        soup = BeautifulSoup(response.text, 'html.parser')
        magnets = set()

        # 1. Look through standard anchor tags
        for a in soup.find_all('a', href=True):
            href = a['href']
            if href.startswith('magnet:?xt=urn:btih:'):
                magnets.add(href.strip())

        # 2. Fallback: Regex scan through raw HTML text for hidden or encoded magnets
        found_matches = re.findall(r'(magnet:\?xt=urn:btih:[a-zA-Z0-9]+[^"\s<]*)', response.text)
        for m in found_matches:
            magnets.add(m.strip())

        return list(magnets)
    except Exception as e:
        print(f"❌ Error scraping inner page {post_url}: {e}")
        return []

def scrape_bulk_movies():
    initialize_firebase()
    ref = db.reference('movies') if firebase_admin._apps else None

    scraped_count = 0
    target_goal = 200  # Target bulk volume requirement

    print(f"🚀 Starting bulk crawler targeting {target_goal}+ items...")

    for category in CATEGORY_PATHS:
        page_num = 1
        while scraped_count < target_goal:
            target_page_url = f"{BASE_URL}{category}page/{page_num}/" if page_num > 1 else f"{BASE_URL}{category}"
            print(f"🔍 Crawling Catalog Index: {target_page_url}")

            try:
                res = requests.get(target_page_url, headers=get_headers(), timeout=15)
                if res.status_code != 200:
                    print(f"⏹️ Reached end of category or block at page {page_num}. Status: {res.status_code}")
                    break

                soup = BeautifulSoup(res.text, 'html.parser')
                
                # Target article/post grid blocks typical of modern DooPlay themes
                posts = soup.find_all(['article', 'div'], class_=re.compile('item|post'))
                if not posts:
                    # Generic fallback loop for links
                    posts = soup.find_all('a', href=True)

                found_on_page = 0
                for post in posts:
                    if scraped_count >= target_goal:
                        break

                    # Extract movie post link and raw title
                    link_tag = post.find('a', href=True) if post.name != 'a' else post
                    if not link_tag:
                        continue
                    
                    post_url = link_tag['href']
                    if not post_url.startswith('http') or '/category/' in post_url or '/tag/' in post_url:
                        continue

                    raw_title = post.get('title') or link_tag.get('text') or "Unknown Title"
                    clean_title = clean_movie_title(raw_title)

                    if len(clean_title) < 2:
                        continue

                    print(processing := f"\n[{scraped_count + 1}] Processing: {clean_title} -> {post_url}")
                    
                    # Parse inner page for permanent Magnets
                    magnets = extract_magnet_from_page(post_url)
                    if not magnets:
                        print("⚠️ No magnet links found. Skipping entry.")
                        time.sleep(0.5)
                        continue

                    print(f"🧲 Found {len(magnets)} permanent Magnet link(s).")

                    # Construct Database Record Payload
                    movie_data = {
                        "title": clean_title,
                        "magnet": magnets if len(magnets) > 1 else magnets[0], # Single string or array
                        "category": "Hindi Dubbed"
                    }

                    # Push/Update to Firebase Database using safe sanitized keys
                    safe_key = re.sub(r'[^a-zA-Z0-9_-]', '_', clean_title.lower())
                    if ref:
                        ref.child(safe_key).set(movie_data)
                        print(f"✅ Successfully synced '{clean_title}' to Firebase!")

                    scraped_count += 1
                    found_on_page += 1
                    time.sleep(1) # Polite crawler interval

                if found_on_page == 0:
                    break # No more posts found on this pagination level

                page_num += 1
            except Exception as e:
                print(f"❌ Error during catalog pagination: {e}")
                break

    print(f"\n🎉 Bulk scraping completed successfully! Total processed: {scraped_count} movies.")

if __name__ == "__main__":
    scrape_bulk_movies()