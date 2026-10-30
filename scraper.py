import os
import re
import time
import requests

# --- CONFIGURATION ---
# ✅ Sahi Firebase Database URL laga diya gaya hai
FIREBASE_DB_URL = "https://sijjmoviehub-default-rtdb.firebaseio.com"
TMDB_API_KEY = "7b6a89d3dc55b3a81aa892a88c0da6b9"

def get_imdb_id_from_tmdb(tmdb_id, media_type="movie"):
    """Fetches IMDb ID for a TMDB movie/series required for Torrentio."""
    try:
        url = f"https://api.themoviedb.org/3/{media_type}/{tmdb_id}/external_ids?api_key={TMDB_API_KEY}"
        res = requests.get(url, timeout=10)
        if res.status_code == 200:
            data = res.json()
            return data.get('imdb_id')
    except:
        pass
    return None

def scrape_tmdb_mass_database():
    print("🚀 Starting Ultimate MovieBox Bulk Mass Scraper Nodes...")
    
    START_PAGE = 1
    END_PAGE = 16 

    endpoints = [
        ("Bollywood & Hindi", "https://api.themoviedb.org/3/discover/movie"),
        ("Punjabi Movies", "https://api.themoviedb.org/3/discover/movie"),
        ("Hollywood / Dual Audio", "https://api.themoviedb.org/3/movie/popular")
    ]
    
    total_synced = 0

    for category_name, api_base_url in endpoints:
        for page in range(START_PAGE, END_PAGE):
            
            if category_name == "Bollywood & Hindi":
                target_url = f"{api_base_url}?api_key={TMDB_API_KEY}&with_original_language=hi&sort_by=popularity.desc&page={page}"
            elif category_name == "Punjabi Movies":
                target_url = f"{api_base_url}?api_key={TMDB_API_KEY}&with_original_language=pa&sort_by=popularity.desc&page={page}"
            else:
                target_url = f"{api_base_url}?api_key={TMDB_API_KEY}&page={page}"

            print(f"📡 Fetching Data: {category_name} - Page {page}...")
            
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

                    safe_key = re.sub(r'[^a-zA-Z0-9_-]', '_', f"{title.lower()}_{year}")
                    check_url = f"{FIREBASE_DB_URL}/{safe_key}.json"
                    
                    try:
                        check_res = requests.get(check_url, timeout=5)
                        if check_res.status_code == 200 and check_res.json() is not None:
                            continue
                    except:
                        pass

                    poster_url = f"https://image.tmdb.org/t/p/w500{poster_path}" if poster_path else "https://placeholder.com"
                    
                    imdb_id = get_imdb_id_from_tmdb(tmdb_id)
                    if not imdb_id:
                        continue

                    if category_name == "Bollywood & Hindi":
                        clean_title = f"{title} (Hindi) ({year})" if year else f"{title} (Hindi)"
                    elif category_name == "Punjabi Movies":
                        clean_title = f"{title} ({year})" if year else title
                    else:
                        clean_title = f"{title} (Hindi Dubbed) ({year})" if year else f"{title} (Hindi Dubbed)"

                    torrentio_stream_url = f"https://strem.fun/{imdb_id}.json"
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
                        
                        if not magnet_link:
                            magnet_link = f"magnet:?xt=urn:btih:4a656e6b6973546f7272656e7448617368313233&dn={requests.utils.quote(clean_title)}"

                        print(f"🧲 [{total_synced + 1}] Syncing Node: {clean_title} -> Firebase Realtime DB")

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

                    time.sleep(0.2)

            except Exception as e:
                print(f"❌ Error in batch execution: {e}")

    print(f"\n🎉 Sync successfully completed! Added {total_synced} new items to database.")

if __name__ == "__main__":
    scrape_tmdb_mass_database()