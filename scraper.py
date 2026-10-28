import os
import re
import time
import requests

# --- CONFIGURATION ---
FIREBASE_DB_URL = "https://sijjmoviehub-default-rtdb.firebaseio.com/movies"
TMDB_API_KEY = "7b6a89d3dc55b3a81aa892a88c0da6b9"

def get_movie_details_from_tmdb(title):
    try:
        clean_search_title = re.sub(r'\s*\(\d{4}\)', '', title).strip()
        search_url = f"https://api.themoviedb.org/3/search/movie?api_key={TMDB_API_KEY}&query={requests.utils.quote(clean_search_title)}"
        
        res = requests.get(search_url, timeout=10)
        if res.status_code == 200:
            data = res.json()
            results = data.get('results', [])
            if results:
                movie = results[0]
                poster_path = movie.get('poster_path')
                poster_url = f"https://image.tmdb.org/t/p/w500{poster_path}" if poster_path else "https://via.placeholder.com/300x450?text=No+Poster"
                original_language = movie.get('original_language', '')
                return poster_url, original_language
    except Exception as e:
        print(f"⚠️ Error fetching TMDB details for {title}: {e}")
    
    return "https://via.placeholder.com/300x450?text=No+Poster", "en"

def scrape_bulk_movies_and_series():
    print("🚀 Starting Mega Bulk Scraper (Hollywood, Bollywood & Punjabi)...")
    
    # Expanded Catalogs including Global, Bollywood, and Punjabi endpoints
    catalogs = [
        "https://v3-cinemeta.strem.io/catalog/movie/top/skip=0.json",
        "https://v3-cinemeta.strem.io/catalog/movie/top/skip=100.json",
        "https://v3-cinemeta.strem.io/catalog/movie/top/skip=200.json",
        "https://v3-cinemeta.strem.io/catalog/series/top/skip=0.json",
        # Cinemeta Indian / Bollywood Catalogs
        "https://v3-cinemeta.strem.io/catalog/movie/top/genre=Hindi/skip=0.json",
        "https://v3-cinemeta.strem.io/catalog/movie/top/genre=Hindi/skip=100.json",
        # Punjabi Cinema endpoint
        "https://v3-cinemeta.strem.io/catalog/movie/top/genre=Punjabi/skip=0.json"
    ]
    
    total_synced = 0

    for catalog_url in catalogs:
        print(f"\n📡 Fetching catalog batch: {catalog_url}")
        try:
            res = requests.get(catalog_url, timeout=15)
            if res.status_code != 200:
                continue

            data = res.json()
            metas = data.get('metas', [])
            if not metas:
                continue

            for item in metas:
                title = item.get('name')
                year = item.get('year')
                genres = item.get('genres', [])
                imdb_id = item.get('id')
                
                if not imdb_id or not title:
                    continue

                poster_url, orig_lang = get_movie_details_from_tmdb(title)

                lower_title = title.lower()
                genre_str = " ".join(genres).lower()

                if 'punjabi' in genre_str or 'punjabi' in lower_title or 'jatt' in lower_title:
                    category = "Punjabi Movies"
                    clean_title = f"{title} ({year})" if year else title
                elif orig_lang in ['hi', 'ur'] or 'hindi' in genre_str or 'bollywood' in genre_str or 'hindi' in lower_title:
                    category = "Bollywood & Hindi"
                    clean_title = f"{title} (Hindi) ({year})" if year else f"{title} (Hindi)"
                else:
                    category = "Hollywood / Dual Audio"
                    clean_title = f"{title} (Hindi Dubbed) ({year})" if year else f"{title} (Hindi Dubbed)"

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

                    print(f"🧲 [{total_synced + 1}] Syncing: {clean_title} [{category}]")

                    movie_data = {
                        "title": clean_title,
                        "magnet": magnet_link,
                        "poster": poster_url,
                        "category": category
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
            print(f"❌ Error in catalog batch: {e}")

    print(f"\n🎉 Mega Scraping Completed! Total {total_synced} items synced to Firebase successfully.")

if __name__ == "__main__":
    scrape_bulk_movies_and_series()