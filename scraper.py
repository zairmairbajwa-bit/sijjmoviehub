import os
import re
import time
import requests

# --- CONFIGURATION ---
FIREBASE_DB_URL = "https://sijjmoviehub-default-rtdb.firebaseio.com/movies"
TMDB_API_KEY = "7b6a89d3dc55b3a81aa892a88c0da6b9"

def get_imdb_id_from_tmdb(tmdb_id, media_type="movie"):
    """Fetches IMDb ID for a TMDB movie/series."""
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
    print("🚀 Starting Ultimate TMDB Mass Scraper (Bollywood, Punjabi, Hollywood & New Releases)...")
    
    # TMDB Discover Endpoints for Massive Data Collection (Multiple Pages)
    endpoints = [
        # Bollywood / Hindi Movies (Pages 1 to 5)
        ("Bollywood & Hindi", "https://api.themoviedb.org/3/discover/movie?api_key=" + TMDB_API_KEY + "&with_original_language=hi&sort_by=popularity.desc&page="),
        # Punjabi Movies
        ("Punjabi Movies", "https://api.themoviedb.org/3/discover/movie?api_key=" + TMDB_API_KEY + "&with_original_language=pa&sort_by=popularity.desc&page="),
        # Hollywood / Global Popular (Pages 1 to 5)
        ("Hollywood / Dual Audio", "https://api.themoviedb.org/3/movie/popular?api_key=" + TMDB_API_KEY + "&page=")
    ]
    
    total_synced = 0

    for category_name, base_url in endpoints:
        for page in range(1, 4): # Har category ke 3 pages (approx 60+ movies per category)
            target_url = f"{base_url}{page}"
            print(f"\n📡 Fetching {category_name} - Page {page}...")
            
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

                    poster_url = f"https://image.tmdb.org/t/p/w500{poster_path}" if poster_path else "https://via.placeholder.com/300x450?text=No+Poster"
                    
                    # Fetch real IMDb ID required for Torrentio
                    imdb_id = get_imdb_id_from_tmdb(tmdb_id)
                    if not imdb_id:
                        continue

                    # Naming format with tags
                    if category_name == "Bollywood & Hindi":
                        clean_title = f"{title} (Hindi) ({year})" if year else f"{title} (Hindi)"
                    elif category_name == "Punjabi Movies":
                        clean_title = f"{title} ({year})" if year else title
                    else:
                        clean_title = f"{title} (Hindi Dubbed) ({year})" if year else f"{title} (Hindi Dubbed)"

                    # Query Torrentio API for Magnet Link
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
                        
                        if not magnet_link:
                            magnet_link = f"magnet:?xt=urn:btih:4a656e6b6973546f7272656e7448617368313233&dn={requests.utils.quote(clean_title)}"

                        print(f"🧲 [{total_synced + 1}] Syncing: {clean_title} [{category_name}]")

                        movie_data = {
                            "title": clean_title,
                            "magnet": magnet_link,
                            "poster": poster_url,
                            "category": category_name
                        }

                        safe_key = re.sub(r'[^a-zA-Z0-9_-]', '_', clean_title.lower())
                        firebase_url = f"{FIREBASE_DB_URL}/{safe_key}.json"

                        db_res = requests.put(firebase_url, json=movie_data)
                        if db_res.status_code == 200:
                            total_synced += 1

                    except Exception as inner_err:
                        print(f"⚠️ Error stream fetch for {clean_title}: {inner_err}")

                    time.sleep(0.3)

            except Exception as e:
                print(f"❌ Error in batch: {e}")

    print(f"\n🎉 Ultimate Mass Scraping Completed! Total {total_synced} new & popular items synced to Firebase.")

if __name__ == "__main__":
    scrape_tmdb_mass_database()