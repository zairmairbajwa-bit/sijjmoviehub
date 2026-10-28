import requests
from bs4 import BeautifulSoup
import re
import time

FIREBASE_BASE_URL = "https://sijjmoviehub-default-rtdb.firebaseio.com/movies"
TMDB_API_KEY = "7b6a89d3dc55b3a81aa892a88c0da6b9"

def get_tmdb_id(movie_title):
    try:
        clean_title = re.sub(r'\b(19|20)\d{2}\b', '', movie_title).strip()
        url = f"https://api.themoviedb.org/3/search/movie?api_key={TMDB_API_KEY}&query={requests.utils.quote(clean_title)}"
        response = requests.get(url, timeout=10).json()
        if response.get('results'):
            return response['results'][0]['id']
    except Exception as e:
        print(f"TMDb API Error: {e}")
    return None

def scrape_movie_page(post_url):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    try:
        res = requests.get(post_url, headers=headers, timeout=15)
        if res.status_code != 200:
            return None
        
        soup = BeautifulSoup(res.text, 'html.parser')
        
        # Title extraction
        title_tag = soup.find('h1', class_='entry-title') or soup.find('h1')
        if not title_tag:
            return None
        movie_title = title_tag.text.strip()
        movie_title = re.sub(r'(Download|Watch Online|Full Movie|Vegamovies).*', '', movie_title, flags=re.IGNORECASE).strip()

        # Magnet link extraction
        magnet_link = None
        for a_tag in soup.find_all('a', href=True):
            if a_tag['href'].startswith('magnet:?xt=urn:btih:'):
                magnet_link = a_tag['href']
                break
        
        if not magnet_link:
            match = re.search(r'(magnet:\?xt=urn:btih:[a-zA-Z0-9]+[^"\s<]*)', res.text)
            if match:
                magnet_link = match.group(1)

        if not magnet_link:
            return None

        # Get TMDb ID
        tmdb_id = get_tmdb_id(movie_title)
        if not tmdb_id:
            return None

        return {
            "id": int(tmdb_id),
            "title": movie_title,
            "url": magnet_link,
            "type": "torrent"
        }
    except Exception as e:
        print(f"Error scraping post {post_url}: {e}")
        return None

def run_bulk_scraper():
    print("🚀 Starting Automated Bulk Torrent Scraper for Vegamovies...")
    base_category_url = "https://vegamovies.ist/category/hindi-dubbed-movies/page/"
    
    saved_count = 0
    # Loop through multiple pages to grab hundreds of movies (e.g., up to page 25 = ~500+ movies)
    for page_num in range(1, 26):
        target_page = f"{base_category_url}{page_num}/"
        print(f"\n📄 Scraping Listing Page {page_num}: {target_page}")
        
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        
        try:
            res = requests.get(target_page, headers=headers, timeout=15)
            if res.status_code != 200:
                print(f"❌ Reached end of pages or failed to load page {page_num}. Status: {res.status_code}")
                break
            
            soup = BeautifulSoup(res.text, 'html.parser')
            
            # Find all movie post links on the category page
            post_links = []
            for a in soup.find_all('a', href=True):
                href = a['href']
                if '/' in href and ('download' in href or 'movie' in href) and href not in post_links:
                    # Filter out category or tag links, keep post links
                    if len(href.split('/')) > 5: 
                        post_links.append(href)
            
            # Remove duplicates
            post_links = list(set(post_links))
            print(f"🔗 Found {len(post_links)} potential movie links on page {page_num}.")

            for post_url in post_links:
                print(f"🔍 Checking movie: {post_url}")
                movie_data = scrape_movie_page(post_url)
                if movie_data:
                    tmdb_id = movie_data['id']
                    firebase_node_url = f"{FIREBASE_BASE_URL}/{tmdb_id}.json"
                    
                    db_res = requests.put(firebase_node_url, json=movie_data)
                    if db_res.status_code == 200:
                        saved_count += 1
                        print(f"✅ Saved [{saved_count}]: {movie_data['title']} (TMDb ID: {tmdb_id})")
                
                time.sleep(1) # Delay to avoid getting blocked
                
        except Exception as e:
            print(f"❌ Error on page {page_num}: {e}")
            continue

    print(f"\n🎉 Bulk Scraping Completed! Total {saved_count} movies successfully saved to Firebase Database.")

if __name__ == "__main__":
    run_bulk_scraper()