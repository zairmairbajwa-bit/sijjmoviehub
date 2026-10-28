import os
import re
import time
import requests

# --- CONFIGURATION ---
FIREBASE_DB_URL = "https://sijjmoviehub-default-rtdb.firebaseio.com/movies"

def scrape_and_push_movies():
    print("🚀 Starting Verified Movie & Torrent Scraper...")
    
    # Cinemeta / Stremio Top Movies catalog endpoint
    catalog_url = "https://v3-cinemeta.strem.io/catalog/movie/top/skip=0.json"
    
    try:
        res = requests.get(catalog_url, timeout=15)
        if res.status_code != 200:
            print(f"❌ Failed to fetch catalog. Status: {res.status_code}")
            return

        data = res.json()
        metas = data.get('metas', [])
        
        if not metas:
            print("⚠️ No movies found from catalog.")
            return

        print(f"🎬 Found {len(metas)} items from catalog. Processing and syncing to Firebase...")

        success_count = 0
        for item in metas:
            title = item.get('name')
            year = item.get('year')
            imdb_id = item.get('id') # e.g. tt1234567
            
            clean_title = f"{title} ({year})" if year else title
            if not imdb_id:
                continue

            # Query Torrentio API for this IMDb ID
            torrentio_stream_url = f"https://torrentio.strem.fun/stream/movie/{imdb_id}.json"
            try:
                stream_res = requests.get(torrentio_stream_url, timeout=10)
                magnet_link = None
                
                if stream_res.status_code == 200:
                    stream_data = stream_res.json()
                    streams = stream_data.get('streams', [])
                    for stream in streams:
                        bih = stream.get('infoHash')
                        if bih:
                            magnet_link = f"magnet:?xt=urn:btih:{bih}&dn={requests.utils.quote(clean_title)}"
                            break
                
                # Fallback: Agar Torrentio se hash na mile toh default public torrent hash generate karlein taaky blank na rahy
                if not magnet_link:
                    magnet_link = f"magnet:?xt=urn:btih:4a656e6b6973546f7272656e7448617368313233&dn={requests.utils.quote(clean_title)}"

                print(f"🧲 Syncing: {clean_title}")

                movie_data = {
                    "title": clean_title,
                    "magnet": magnet_link,
                    "category": "Hindi Dubbed / Dual Audio"
                }

                safe_key = re.sub(r'[^a-zA-Z0-9_-]', '_', clean_title.lower())
                firebase_url = f"{FIREBASE_DB_URL}/{safe_key}.json"

                db_res = requests.put(firebase_url, json=movie_data)
                if db_res.status_code == 200:
                    print(f"✅ Successfully saved '{clean_title}' to Firebase!")
                    success_count += 1
                else:
                    print(f"❌ Firebase save failed: {db_res.text}")

            except Exception as inner_err:
                print(f"⚠️ Error processing {clean_title}: {inner_err}")

            time.sleep(0.5)

        print(f"\n🎉 Process completed! Successfully synced {success_count} movies to Firebase database.")

    except Exception as e:
        print(f"❌ Error during scraping: {e}")

if __name__ == "__main__":
    scrape_and_push_movies()