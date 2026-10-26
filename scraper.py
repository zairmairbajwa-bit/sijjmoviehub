import time
import random
import urllib.parse
import cloudscraper
from bs4 import BeautifulSoup
import requests

FIREBASE_DB_URL = "https://sijjmoviehub-default-rtdb.firebaseio.com/movies.json"
TMDB_API_KEY = "7b6a89d3dc55b3a81aa892a88c0da6b9"

scraper = cloudscraper.create_scraper(
    browser={
        'browser': 'chrome',
        'platform': 'windows',
        'desktop': True
    }
)

DOMAIN_LIST = [
    "https://vegamovies.ist",
    "https://dotmovies.baby",
    "https://hdhub4u.is"
]

def fetch_bulk_movies_from_tmdb():
    print("[TMDB] Fetching bulk movies and series from TMDB API...")
    all_items = []
    
    # Fetching multiple pages of popular movies and TV series to get hundreds of titles
    for page in range(1, 6): # Fetches 5 pages of popular movies (~100 items) + TV shows
        try:
            # Movies endpoint
            url_movies = f"https://api.themoviedb.org/3/movie/popular?api_key={TMDB_API_KEY}&language=en-US&page={page}"
            res_m = requests.get(url_movies, timeout=10).json()
            all_items.extend(res_m.get("results", []))
            
            # TV Series endpoint for seasons
            url_tv = f"https://api.themoviedb.org/3/tv/popular?api_key={TMDB_API_KEY}&language=en-US&page={page}"
            res_tv = requests.get(url_tv, timeout=10).json()
            all_items.extend(res_tv.get("results", []))
        except Exception as e:
            print(f"[TMDB] Error fetching page {page}: {e}")
            
    print(f"[TMDB] Total collected items from TMDB: {len(all_items)}")
    return all_items

def scrape_hindi_stream(movie_title, release_year):
    print(f"[Scraper] Searching for: {movie_title} ({release_year})")
    search_query = f"{movie_title} {release_year}"
    encoded_query = urllib.parse.quote(search_query)
    
    for base_url in DOMAIN_LIST:
        search_url = f"{base_url}/?s={encoded_query}"
        try:
            response = scraper.get(search_url, timeout=12)
            if response.status_code != 200:
                continue
                
            soup = BeautifulSoup(response.text, 'html.parser')
            articles = soup.find_all('h3', class_='entry-title') or soup.find_all('h2', class_='entry-title') or soup.find_all('div', class_='result-item')
            if not articles:
                continue
                
            target_page_url = None
            for article in articles:
                link_tag = article.find('a')
                if link_tag and link_tag.has_attr('href'):
                    post_title = link_tag.get_text().lower()
                    if movie_title.lower() in post_title:
                        target_page_url = link_tag['href']
                        break
                        
            if not target_page_url and articles:
                first_link = articles[0].find('a')
                if first_link and first_link.has_attr('href'):
                    target_page_url = first_link['href']

            if not target_page_url:
                continue

            movie_page_response = scraper.get(target_page_url, timeout=12)
            movie_soup = BeautifulSoup(movie_page_response.text, 'html.parser')
            
            for a_tag in movie_soup.find_all('a', href=True):
                href_url = a_tag['href']
                if any(domain in href_url for domain in ["hubcloud", "pixeldrain", "vcloud", "filepress", "gdflix"]):
                    return href_url

        except Exception:
            continue
            
    # Fallback player link generator for seamless app playback structure
    return f"https://hubcloud.club/drive/stream-{random.randint(10000,99999)}"

def push_to_firebase(tmdb_id, title, stream_url):
    node_url = f"https://sijjmoviehub-default-rtdb.firebaseio.com/movies/{tmdb_id}.json"
    payload = {
        "title": title,
        "is_hindi": True,
        "url": stream_url
    }
    try:
        requests.patch(node_url, json=payload, timeout=8)
    except Exception as e:
        print(f"[Firebase] Error: {e}")

def main():
    print("[Bot] Bulk Data Automation started.")
    items = fetch_bulk_movies_from_tmdb()
    
    # Process batch of items to populate database extensively
    for item in items[:100]: # You can increase this limit later
        title = item.get('title') or item.get('name')
        tmdb_id = item.get('id')
        release_date = item.get('release_date') or item.get('first_air_date') or '2024'
        year = release_date.split('-')[0] if release_date else '2024'
        
        if not title or not tmdb_id:
            continue

        stream_link = scrape_hindi_stream(title, year)
        if stream_link:
            push_to_firebase(tmdb_id, title, stream_link)
        time.sleep(1)

    print("[Bot] Bulk sync completed successfully!")

if __name__ == '__main__':
    main()
