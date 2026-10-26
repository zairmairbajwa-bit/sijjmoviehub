from flask import Flask, jsonify
import threading
import time
import random
import urllib.parse
import cloudscraper
from bs4 import BeautifulSoup
import requests

app = Flask(__name__)

FIREBASE_DB_URL = "https://sijjmoviehub-default-rtdb.firebaseio.com/movies.json"
TMDB_API_KEY = "7b6a89d3dc55b3a81aa892a88c0da6b9"

scraper = cloudscraper.create_scraper(
    browser={
        'browser': 'chrome',
        'platform': 'windows',
        'desktop': True
    }
)

BASE_URL = "https://vegamovies.mex"

INITIAL_MOVIES = [
    {"title": "Avatar: The Way of Water", "id": "76600", "year": "2022"},
    {"title": "Avengers: Endgame", "id": "299534", "year": "2019"},
    {"title": "Oppenheimer", "id": "872585", "year": "2023"},
    {"title": "Interstellar", "id": "157336", "year": "2014"},
    {"title": "The Batman", "id": "414906", "year": "2022"},
    {"title": "John Wick Chapter 4", "id": "603692", "year": "2023"}
]

def fetch_trending_from_tmdb():
    print("[TMDB] Fetching trending movies from TMDB API...")
    url = f"https://api.themoviedb.org/3/trending/all/day?api_key={TMDB_API_KEY}&language=en-US"
    try:
        response = requests.get(url, timeout=10)
        data = response.json()
        results = data.get("results", [])
        print(f"[TMDB] Successfully fetched {len(results)} items.")
        return results
    except Exception as e:
        print(f"[TMDB] Error fetching trending list: {e}")
        return []

def scrape_hindi_stream(movie_title, release_year):
    print(f"[Scraper] Searching for movie: {movie_title} ({release_year})")
    search_query = f"{movie_title} {release_year} Hindi"
    encoded_query = urllib.parse.quote(search_query)
    search_url = f"{BASE_URL}/?s={encoded_query}"
    
    try:
        response = scraper.get(search_url, timeout=15)
        if response.status_code != 200:
            print(f"[Scraper] Cloudflare block or status code {response.status_code} for {movie_title}")
            return None
            
        soup = BeautifulSoup(response.text, 'html.parser')
        articles = soup.find_all('h3', class_='entry-title') or soup.find_all('h2', class_='entry-title')
        if not articles:
            print(f"[Scraper] No search result articles found on site for {movie_title}")
            return None
            
        target_page_url = None
        for article in articles:
            link_tag = article.find('a')
            if link_tag:
                post_title = link_tag.get_text().lower()
                if movie_title.lower() in post_title:
                    target_page_url = link_tag['href']
                    break
                    
        if not target_page_url:
            target_page_url = articles[0].find('a')['href']

        print(f"[Scraper] Opening target post page: {target_page_url}")
        movie_page_response = scraper.get(target_page_url, timeout=15)
        movie_soup = BeautifulSoup(movie_page_response.text, 'html.parser')
        
        final_stream_url = None
        for a_tag in movie_soup.find_all('a', href=True):
            href_url = a_tag['href']
            if "hubcloud" in href_url or "pixeldrain" in href_url or "vcloud" in href_url or "drive" in href_url:
                if "hubcloud" in href_url and "drive" in href_url:
                    continue
                final_stream_url = href_url
                break
                
        if final_stream_url:
            print(f"[Scraper] Link found! -> {final_stream_url}")
        else:
            print(f"[Scraper] No matching cloud stream link found inside the post.")
            
        return final_stream_url

    except Exception as e:
        print(f"[Scraper] Error during scraping for {movie_title}: {str(e)}")
        return None

def push_to_firebase(tmdb_id, title, stream_url):
    node_url = f"https://sijjmoviehub-default-rtdb.firebaseio.com/movies/{tmdb_id}.json"
    payload = {
        "title": title,
        "is_hindi": True,
        "url": stream_url
    }
    print(f"[Firebase] Pushing data for '{title}' (ID: {tmdb_id})...")
    try:
        response = requests.patch(node_url, json=payload, timeout=10)
        if response.status_code == 200:
            print(f"[Firebase] Firebase push successful for {title}!")
        else:
            print(f"[Firebase] Failed to push {title}. Status code: {response.status_code}")
    except Exception as e:
        print(f"[Firebase] Firebase connection error: {e}")

def background_automation():
    print("[Bot] Background Automation loop started.")
    time.sleep(2)
    
    # 1. Process initial movies immediately
    print("[Bot] Processing initial movie list...")
    for movie in INITIAL_MOVIES:
        title = movie["title"]
        tmdb_id = movie["id"]
        year = movie["year"]
        
        stream_link = scrape_hindi_stream(title, year)
        if stream_link:
            push_to_firebase(tmdb_id, title, stream_link)
        else:
            print(f"[Bot] Skipping initial movie {title} due to missing stream.")
        
        time.sleep(random.randint(2, 4))

    # 2. Continuous trending check loop
    while True:
        print("[Bot] Starting new TMDB trending batch check...")
        movies = fetch_trending_from_tmdb()
        
        for item in movies:
            title = item.get('title') or item.get('name')
            tmdb_id = item.get('id')
            release_date = item.get('release_date') or item.get('first_air_date') or '2024'
            year = release_date.split('-')[0]
            
            if not title or not tmdb_id:
                continue

            stream_link = scrape_hindi_stream(title, year)
            
            if stream_link:
                push_to_firebase(tmdb_id, title, stream_link)
            else:
                print(f"[Bot] No stream found for {title}.")
            
            time.sleep(random.randint(5, 8))
            
        print("[Bot] Batch complete. Waiting 15 minutes before next check...")
        time.sleep(900)

# Global thread launcher taaky Gunicorn worker start hone ke sath hi background bot chal paray
def start_background_bot():
    global bot_started
    try:
        if not bot_started:
            bot_started = True
            t = threading.Thread(target=background_automation)
            t.daemon = True
            t.start()
            print("[System] Background automation thread successfully triggered.")
    except Exception as e:
        print(f"[System] Error starting background thread: {e}")

bot_started = False
start_background_bot()

@app.route('/')
def home():
    start_background_bot() # Double safety taaky koi bhi HTTP hit aane par bhi bot active ho jaye
    return jsonify({"status": "Bot Automation is Active and Running!"})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)