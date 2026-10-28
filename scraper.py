import os
import re
import time
import requests
import cloudscraper
from bs4 import BeautifulSoup

# --- CONFIGURATION ---
BASE_URL = "https://vegamovies.network"
CATEGORY_PATHS = [
    "/hindi-dubbed/",
    "/dual-audio-movies/"
]
FIREBASE_DB_URL = "https://sijjmoviehub-default-rtdb.firebaseio.com/movies"

def get_scraper():
    """Creates a cloudscraper instance to bypass Cloudflare 403 blocks."""
    scraper = cloudscraper.create_scraper(
        browser={
            'browser': 'chrome',
            'platform': 'windows',
            'desktop': True
        }
    )
    return scraper

def clean_movie_title(raw_title):
    title = re.sub(r'(Download|Full Movie|Vegamovies|Dual Audio|Hindi|English|WEB-DL|HDRip|BluRay|480p|720p|1080p).*', '', raw_title, flags=re.IGNORECASE)
    return title.strip(" -|[]()")

def extract_magnet_from_page(scraper, post_url):
    try:
        response = scraper.get(post_url, timeout=20)
        if response.status_code != 200:
            return []
        
        soup = BeautifulSoup(response.text, 'html.parser')
        magnets = set()

        for a in soup.find_all('a', href=True):
            href = a['href']
            if href.startswith('magnet:?xt=urn:btih:'):
                magnets.add(href.strip())

        found_matches = re.findall(r'(magnet:\?xt=urn:btih:[a-zA-Z0-9]+[^"\s<]*)', response.text)
        for m in found_matches:
            magnets.add(m.strip())

        return list(magnets)
    except Exception as e:
        print(f"❌ Error scraping inner page {post_url}: {e}")
        return []

def scrape_bulk_movies():
    scraper = get_scraper()
    scraped_count = 0
    target_goal = 20  # Test ke liye 20 movies

    print(f"🚀 Starting cloudscraper-powered crawler targeting {target_goal} items...")

    for category in CATEGORY_PATHS:
        page_num = 1
        while scraped_count < target_goal:
            target_page_url = f"{BASE_URL}{category}page/{page_num}/" if page_num > 1 else f"{BASE_URL}{category}"
            print(f"🔍 Crawling Catalog Index: {target_page_url}")

            try:
                res = scraper.get(target_page_url, timeout=20)
                print(f"📡 Response Status Code: {res.status_code}")
                
                if res.status_code != 200:
                    print(f"⏹️ Blocked or reached end (Status {res.status_code}). Stopping category.")
                    break

                soup = BeautifulSoup(res.text, 'html.parser')
                posts = soup.find_all(['article', 'div'], class_=re.compile('item|post'))
                if not posts:
                    posts = soup.find_all('a', href=True)

                found_on_page = 0
                for post in posts:
                    if scraped_count >= target_goal:
                        break

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

                    print(f"\n[{scraped_count + 1}] Processing: {clean_title}")
                    
                    magnets = extract_magnet_from_page(scraper, post_url)
                    if not magnets:
                        print("⚠️ No magnet links found. Skipping.")
                        time.sleep(1)
                        continue

                    print(f"🧲 Found {len(magnets)} permanent Magnet link(s).")

                    movie_data = {
                        "title": clean_title,
                        "magnet": magnets if len(magnets) > 1 else magnets[0],
                        "category": "Hindi Dubbed"
                    }

                    safe_key = re.sub(r'[^a-zA-Z0-9_-]', '_', clean_title.lower())
                    firebase_url = f"{FIREBASE_DB_URL}/{safe_key}.json"
                    
                    db_res = requests.put(firebase_url, json=movie_data)
                    if db_res.status_code == 200:
                        print(f"✅ Successfully synced '{clean_title}' to Firebase!")
                    else:
                        print(f"❌ Firebase save failed: {db_res.text}")

                    scraped_count += 1
                    found_on_page += 1
                    time.sleep(2)

                if found_on_page == 0:
                    break

                page_num += 1
            except Exception as e:
                print(f"❌ Error during pagination: {e}")
                break

    print(f"\n🎉 Bulk scraping completed! Total processed: {scraped_count} movies.")

if __name__ == "__main__":
    scrape_bulk_movies()