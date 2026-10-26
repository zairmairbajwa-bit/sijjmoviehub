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

def fetch_trending_from_tmdb():
    url = f"https://api.themoviedb.org/3/trending/all/day?api_key={TMDB_API_KEY}&language=en-US"
    try:
        response = requests.get(url, timeout=10)
        data = response.json()
        return data.get("results", [])
    except Exception as e:
        print(f"Error fetching TMDB trending list: {e}")
        return []

def scrape_hindi_stream(movie_title, release_year):
    search_query = f"{movie_title} {release_year} Hindi"
    encoded_query = urllib.parse.quote(search_query)
    search_url = f"{BASE_URL}/?s={encoded_query}"
    
    try:
        response = scraper.get(search_url, timeout=15)
        if response.status_code != 200:
            print(f"Cloudflare block or status code {response.status_code} for {movie_title}")
            return None
            
        soup = BeautifulSoup(response.text, 'html.parser')
        articles = soup.find_all('h3', class_='entry-title') or soup.find_all('h2', class_='entry-title')
        if not articles:
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
                
        return final_stream_url

    except Exception as e:
        print(f"Scraper error for {movie_title}: {str(e)}")
        return None

def push_to_firebase(tmdb_id, title, stream_url):
    node_url = f"https://sijjmoviehub-default-rtdb.firebaseio.com/movies/{tmdb_id}.json"
    payload = {
        "title": title,
        "is_hindi": True,
        "url": stream_url
    }
    try:
        response = requests.patch(node_url, json=payload, timeout=10)
        if response.status_code == 200:
            print(f"Successfully pushed to Firebase: {title} (ID: {tmdb_id})")
        else:
            print(f"Failed to push {title}. Status code: {response.status_code}")
    except Exception as e:
        print(f"Firebase connection error: {e}")

def background_automation():
    print("Safe Background Bot Automation started...")
    time.sleep(5)
    while True:
        movies = fetch_trending_from_tmdb()
        print(f"Fetched {len(movies)} items from TMDB to process.")
        
        for item in movies:
            title = item.get('title') or item.get('name')
            tmdb_id = item.get('id')
            release_date = item.get('release_date') or item.get('first_air_date') or '2024'
            year = release_date.split('-')[0]
            
            if not title or not tmdb_id:
                continue

            print(f"Checking stream for: {title} ({year})")
            stream_link = scrape_hindi_stream(title, year)
            
            if stream_link:
                print(f"Found Hindi Stream! Uploading...")
                push_to_firebase(tmdb_id, title, stream_link)
            else:
                print(f"No Hindi stream found for {title}.")
            
            # Har request ke darmiyan 5 se 10 second ka random gap taaky ban ya block na ho
            sleep_time = random.randint(5, 10)
            time.sleep(sleep_time)
            
        print("Batch complete. Waiting 30 minutes before next check...")
        time.sleep(1800) # 30 min ka safe break taaky server normal rahay

@app.route('/')
def home():
    return jsonify({"status": "Safe Bot Server is Running!"})

if __name__ == '__main__':
    t = threading.Thread(target=background_automation)
    t.daemon = True
    t.start()
    
    app.run(host='0.0.0.0', port=5000)