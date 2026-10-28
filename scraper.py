import os
import re
import time
import requests

# --- CONFIGURATION ---
# Torrentio public instance endpoint for popular/trending movies
TORRENTIO_API_URL = "https://torrentio.strem.fun/stream/movie/tt0111161.json" # Example query or catalog endpoint
# Alternative: We can query via Stremio Cinemeta + Torrentio combined API or direct torrent providers
# Let's use a robust public Torrentio search endpoint or direct Stremio addon resolver
FIREBASE_DB_URL = "https://sijjmoviehub-default-rtdb.firebaseio.com/movies"

def scrape_torrentio_movies():
    print("🚀 Starting Torrentio API Movie Scraper...")
    
    # Torrentio works best when queried with specific IMDb IDs or via Stremio catalogs.
    # To fetch bulk Hindi/Hollywood items cleanly, let's use a curated list or public catalog proxy API.
    catalog_url = "https://v3-cinemeta.strem.io/catalog/movie/top/skip=0.json"
    
    try:
        res = requests.get(catalog_url, timeout=15)
        if res.status_code != 200:
            print(f"❌ Failed to fetch Cinemeta/Torrentio catalog. Status: {res.status_code}")
            return

        data = res.json()
        metas = data.get('metas', [])
        
        if not metas:
            print("⚠️ No movies found from catalog.")
            return

        print(f"🎬 Found {len(metas)} movies. Resolving streams via Torrentio...")

        for item in metas:
            title = item.get('name')
            year = item.get('year')
            imdb_id = item.get('id') # e.g. tt1234567
            
            clean_title = f"{title} ({year})" if year else title
            if not imdb_id:
                continue

            # Query Torrentio API for this specific IMDb ID to get real Magnet/Torrent streams
            torrentio_stream_url = f"https://torrentio.strem.fun/stream/movie/{imdb_id}.json"
            stream_res = requests.get(torrentio_stream_url, timeout=10)
            
            if stream_res.status_code != 200:
                continue

            stream_data = stream_res.json()
            streams = stream_data.get('streams', [])
            
            magnet_link = None
            for stream in streams:
                # Look for torrent infoHash or direct magnet link in stream details
                bih = stream.get('infoHash')
                if bih:
                    magnet_link = f"magnet:?xt=urn:btih:{bih}&dn={requests.utils.quote(clean_title)}"
                    break

            if not magnet_link:
                continue

            print(f"🧲 Found Magnet for: {clean_title}")

            movie_data = {
                "title": clean_title,
                "magnet": magnet_link,
                "category": "Hindi Dubbed / Dual Audio"
            }

            safe_key = re.sub(r'[^a-zA-Z0-9_-]', '_', clean_title.lower())
            firebase_url = f"{FIREBASE_DB_URL}/{safe_key}.json"

            db_res = requests.put(firebase_url, json=movie_data)
            if db_res.status_code == 200:
                print(f"✅ Synced '{clean_title}' to Firebase!")
            else:
                print(f"❌ Firebase save failed: {db_res.text}")

            time.sleep(1)

        print("\n🎉 Torrentio scraping and syncing completed successfully!")

    except Exception as e:
        print(f"❌ Error during Torrentio scraping: {e}")

if __name__ == "__main__":
    scrape_torrentio_movies()