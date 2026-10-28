import os
import re
import time
import requests

# --- CONFIGURATION ---
# YTS Public API Endpoint (Unlimited, No Cloudflare blocks)
YTS_API_URL = "https://yts.mx/api/v2/list_movies.json?sort_by=download_count&limit=50"
FIREBASE_DB_URL = "https://sijjmoviehub-default-rtdb.firebaseio.com/movies"

def scrape_yts_movies():
    print("🚀 Starting YTS API Movie Scraper...")
    
    try:
        response = requests.get(YTS_API_URL, timeout=15)
        if response.status_code != 200:
            print(f"❌ Failed to fetch from YTS API. Status: {response.status_code}")
            return

        data = response.json()
        movies = data.get('data', {}).get('movies', [])
        
        if not movies:
            print("⚠️ No movies returned from YTS API.")
            return

        print(f"🎬 Found {len(movies)} movies from YTS. Processing and syncing to Firebase...")

        for movie in movies:
            title = movie.get('title_english') or movie.get('title')
            year = movie.get('year')
            clean_title = f"{title} ({year})" if year else title
            
            torrents = movie.get('torrents', [])
            if not torrents:
                continue

            # Get the best quality magnet link (prefer 720p or 1080p)
            best_torrent = torrents[0] # Default first
            for t in torrents:
                if '1080p' in t.get('quality', ''):
                    best_torrent = t
                    break

            # Construct official magnet link using hash
            torrent_hash = best_torrent.get('hash')
            if not torrents or not torrent_hash:
                continue

            # Standard BitTorrent magnet link format
            magnet_link = f"magnet:?xt=urn:btih:{torrent_hash}&dn={requests.utils.quote(clean_title)}"

            print(f"🧲 Processing: {clean_title}")

            movie_data = {
                "title": clean_title,
                "magnet": magnet_link,
                "category": "Hollywood / English"
            }

            # Save directly to Firebase Realtime Database via REST API
            safe_key = re.sub(r'[^a-zA-Z0-9_-]', '_', clean_title.lower())
            firebase_url = f"{FIREBASE_DB_URL}/{safe_key}.json"

            db_res = requests.put(firebase_url, json=movie_data)
            if db_res.status_code == 200:
                print(f"✅ Synced '{clean_title}' to Firebase!")
            else:
                print(f"❌ Firebase save failed: {db_res.text}")

            time.sleep(0.5)

        print("\n🎉 YTS Movie scraping and syncing completed successfully!")

    except Exception as e:
        print(f"❌ Error during YTS scraping: {e}")

if __name__ == "__main__":
    scrape_yts_movies()