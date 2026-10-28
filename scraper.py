import requests
from bs4 import BeautifulSoup
import re

# Configuration
FIREBASE_BASE_URL = "https://sijjmoviehub-default-rtdb.firebaseio.com/movies"
TMDB_API_KEY = "7b6a89d3dc55b3a81aa892a88c0da6b9"  # Aapki app wali TMDb API key

def get_tmdb_id(movie_title):
    """Helper function to search TMDb and get the official movie ID using title"""
    try:
        # Clean title for better search results (remove years or tags if present)
        clean_title = re.sub(r'\b(19|20)\d{2}\b', '', movie_title).strip()
        url = f"https://api.themoviedb.org/3/search/movie?api_key={TMDB_API_KEY}&query={requests.utils.quote(clean_title)}"
        response = requests.get(url).json()
        if response.get('results'):
            return response['results'][0]['id']
    except Exception as e:
        print(f"TMDb API Error: {e}")
    return None

def scrape_vegamovies_torrent(page_url, manual_tmdb_id=None):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    print(f"🔍 Scraping URL: {page_url}")
    response = requests.get(page_url, headers=headers)
    if response.status_code != 200:
        print(f"❌ Failed to fetch page. Status code: {response.status_code}")
        return

    soup = BeautifulSoup(response.text, 'html.parser')

    # 1. Extract Movie Title
    title_tag = soup.find('h1', class_='entry-title') or soup.find('h1')
    movie_title = title_tag.text.strip() if title_tag else "Unknown Movie"
    # Clean up junk text from WordPress title
    movie_title = re.sub(r'(Download|Watch Online|Full Movie|Vegamovies).*', '', movie_title, flags=re.IGNORECASE).strip()
    print(f"🎬 Found Movie Title: {movie_title}")

    # 2. Extract Magnet Link
    magnet_link = None
    
    # Search in all <a> tags first
    for a_tag in soup.find_all('a', href=True):
        href = a_tag['href']
        if href.startswith('magnet:?xt=urn:btih:'):
            magnet_link = href
            break

    # Fallback: Search inside raw HTML text via regex if <a> tag didn't contain it directly
    if not magnet_link:
        match = re.search(r'(magnet:\?xt=urn:btih:[a-zA-Z0-9]+[^"\s<]*)', response.text)
        if match:
            magnet_link = match.group(1)

    if not magnet_link:
        print("❌ No Magnet Link found on this Vegamovies page.")
        return

    print(f"🧲 Found Magnet Link: {magnet_link[:60]}...")

    # 3. Get TMDb ID
    tmdb_id = manual_tmdb_id
    if not tmdb_id:
        print("🔎 Searching TMDb ID automatically...")
        tmdb_id = get_tmdb_id(movie_title)

    if not tmdb_id:
        print("⚠️ Could not find a matching TMDb ID. Skipping database save.")
        return

    print(f"🆔 TMDb ID: {tmdb_id}")

    # 4. Save to Firebase Realtime Database
    # Stored directly under the movie's TMDb ID node so the app matches it seamlessly
    firebase_node_url = f"{FIREBASE_BASE_URL}/{tmdb_id}.json"
    
    payload = {
        "id": int(tmdb_id),
        "title": movie_title,
        "url": magnet_link,  # Permanent magnet link
        "type": "torrent"
    }

    db_response = requests.put(firebase_node_url, json=payload)
    if db_response.status_code == 200:
        print(f"✅ Successfully saved '{movie_title}' to Firebase Realtime Database!")
    else:
        print(f"❌ Failed to save to Firebase: {db_response.text}")

if __name__ == "__main__":
    target_url = input("Enter Vegamovies Post URL: ").strip()
    manual_id = input("Enter TMDb ID manually (Press Enter to auto-detect): ").strip()
    
    scrape_vegamovies_torrent(target_url, int(manual_id) if manual_id else None)
