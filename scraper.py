import os
import requests
import json

TMDB_API_KEY = "7b6a89d3dc55b3a81aa892a88c0da6b9"
FIREBASE_URL = "https://sijjmoviehub-default-rtdb.firebaseio.com"

def fetch_and_sync_metadata():
    """
    Fetches trending clean structural metadata from TMDB and syncs to Firebase Realtime Database.
    No static streaming URLs are saved to prevent token expiration crashes.
    """
    url = f"https://api.themoviedb.org/3/trending/movie/day?api_key={TMDB_API_KEY}"
    try:
        response = requests.get(url)
        if response.status_code != 200:
            print("Failed to fetch trending movies from TMDB API.")
            return
        
        data = response.json()
        movies = data.get("results", [])

        for movie in movies:
            tmdb_id = movie.get("id")
            title = movie.get("title") or movie.get("name") or "Untitled"
            overview = movie.get("overview") or ""
            release_date = movie.get("release_date") or ""
            poster_path = movie.get("poster_path")
            poster_url = f"https://image.tmdb.org/t/p/w500{poster_path}" if poster_path else "https://via.placeholder.com/300x450?text=No+Poster"
            
            # Automated translation check block targeting TMDB /movie/{id}/translations for Hindi audio
            trans_url = f"https://api.themoviedb.org/3/movie/{tmdb_id}/translations?api_key={TMDB_API_KEY}"
            trans_res = requests.get(trans_url)
            has_hindi = False
            if trans_res.status_code == 200:
                translations = trans_res.json().get("translations", [])
                has_hindi = any(t.get("iso_639_1") == "hi" for t in translations)

            movie_document = {
                "tmdb_id": str(tmdb_id),
                "title": title,
                "overview": overview,
                "release_date": release_date,
                "poster": poster_url,
                "hindi_dubbed": has_hindi,
                "category": "Trending Hollywood (Hindi Dubbed)" if has_hindi else "Popular Updates"
            }

            # Push clean metadata document to Firebase
            endpoint = f"{FIREBASE_URL}/movies/{tmdb_id}.json"
            res = requests.put(endpoint, data=json.dumps(movie_document))
            if res.status_code == 200:
                print(f"Synced Metadata Successfully: {title} [Hindi Dubbed: {has_hindi}]")
            else:
                print(f"Failed to sync {title}: {res.status_code}")

    except Exception as e:
        print(f"Scraper execution exception: {e}")

if __name__ == "__main__":
    print("Starting Zero-Database-Link Metadata Scraper Bot...")
    fetch_and_sync_metadata()
    print("Metadata synchronization completed!")