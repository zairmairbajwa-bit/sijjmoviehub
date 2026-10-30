import os
import re
import time
import requests

# --- CONFIGURATION ---
FIREBASE_DB_URL = "https://firebaseio.com"
TMDB_API_KEY = "7b6a89d3dc55b3a81aa892a88c0da6b9"

def get_imdb_id_from_tmdb(tmdb_id, media_type="movie"):
    """Fetches IMDb ID for a TMDB movie/series required for Torrentio."""
    try:
        url = f"https://themoviedb.org{media_type}/{tmdb_id}/external_ids?api_key={TMDB_API_KEY}"
        res = requests.get(url, timeout=10)
        if res.status_code == 200:
            data = res.json()
            return data.get('imdb_id')
    except:
        pass
    return None

def scrape_tmdb_mass_database():
    print("🚀 Starting Ultimate MovieBox Bulk Mass Scraper Nodes...")
    
    # 1000+ entries tak load karne ke liye pages ki range ko 15 tak set kiya hai
    START_PAGE = 1
    END_PAGE = 16 

    endpoints = [
        ("Bollywood & Hindi", "https://themoviedb.orgdiscover/movie?api_key=" + TMDB_API_KEY + "&with_original_language=hi&sort_by=popularity.desc&page="),
        ("Punjabi Movies", "https://themoviedb.orgdiscover/movie?api_key=" + TMDB_API_KEY + "&with_original_language=pa&sort_by=popularity.desc&page="),
        ("Hollywood / Dual Audio", "https://themoviedb.orgmovie/popular?api_key=" + TMDB_API_KEY + "&page=")
    ]
    
    total_synced = 0

    for category_name, base_url in endpoints:
        for page in range(START_PAGE, END_PAGE):
            target_url = f"{base_url}{page}"
            print(f"\n📡 Fetching Data: {category_name} - Page {page}...")
            
            try:
                res = requests.get(target_url, timeout=15)
                if res.status_code != 200:
                    continue

                data = res.json()
                results = data.get('results', [])
                if not results:
                    continue

                for item in results:
                    title = item.get('title') or item.get('name')
                    release_date = item.get('release_date') or item.get('first_air_date', '')
                    year = release_date.split('-')[0] if release_date else ''
                    tmdb_id = item.get('id')
                    poster_path = item.get('poster_path')
                    
                    if not tmdb_id or not title:
                        continue

                    # Firebase Realtime Database Data Duplicate check filter
                    safe_key = re.sub(r'[^a-zA-Z0-9_-]', '_', f"{title.lower()}_{year}")
                    check_url = f"{FIREBASE_DB_URL}/{safe_key}.json"
                    
                    check_res = requests.get(check_url, timeout=5)
                    if check_res.status_code == 200 and check_res.json() is not None:
                        # Agar movie pehle se saved hai to time zaya kiye bina skip karo
                        continue

                    poster_url = f"https://tmdb.org{poster_path}" if poster_path else "https://placeholder.com"
                    
                    imdb_id = get_imdb_id_from_tmdb(tmdb_id)
                    if not imdb_id:
                        continue

                    if category_name == "Bollywood & Hindi":
                        clean_title = f"{title} (Hindi) ({year})" if year else f"{title} (Hindi)"
                    elif category_name == "Punjabi Movies":
                        clean_title = f"{title} ({year})" if year else title
                    else:
                        clean_title = f"{title} (Hindi Dubbed) ({year})" if year else f"{title} (Hindi Dubbed)"

                    torrentio_stream_url = f"https://strem.fun{imdb_id}.json"
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
                        
                        # Fallback Link if infohash is missing
                        if not magnet_link:
                            magnet_link = f"magnet:?xt=urn:btih:4a656e6b6973546f7272656e7448617368313233&dn={requests.utils.quote(clean_title)}"

                        print(f"🧲 [{total_synced + 1}] Syncing Node: {clean_title} -> Firebase Realtime DB")

                        # App ke codes aur schema ke mutabiq values set hain
                        movie_data = {
                            "title": clean_title,
                            "terabox_url": magnet_link, 
                            "poster": poster_url,
                            "category": "Trending" if page <= 3 else "New",
                            "tmdb_id": str(tmdb_id)
                        }

                        firebase_url = f"{FIREBASE_DB_URL}/{safe_key}.json"
                        db_res = requests.put(firebase_url, json=movie_data)
                        if db_res.status_code == 200:
                            total_synced += 1

                    except Exception as inner_err:
                        print(f"⚠️ Error stream fetch for {clean_title}: {inner_err}")

                    time.sleep(0.2) # Delay taake API block na ho

            except Exception as e:
                print(f"❌ Error in batch execution: {e}")

    print(f"\n🎉 Sync successfully completed! Added {total_synced} new items to database.")

# --- MAIN RUN ENGINE FOR GITHUB ACTIONS ---
if __name__ == "__main__":
    scrape_tmdb_mass_database()
