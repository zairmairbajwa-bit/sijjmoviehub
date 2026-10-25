from flask import Flask, jsonify, request
import cloudscraper
from bs4 import BeautifulSoup
import urllib.parse
import re

app = Flask(__name__)
# Cloudflare protection bypass karne ke liye advanced web scraper setup
scraper = cloudscraper.create_scraper(
    browser={
        'browser': 'chrome',
        'platform': 'windows',
        'desktop': True
    }
)

# Active streaming network target portal
BASE_URL = "https://vegamovies.mex" # Agar inka domain badle to aap bas domain change kar dena

def scrape_hindi_links(movie_title, release_year):
    # Perfect query structure banana taaky Hindi dubbed result hi mile
    search_query = f"{movie_title} {release_year} Hindi"
    encoded_query = urllib.parse.quote(search_query)
    search_url = f"{BASE_URL}/?s={encoded_query}"
    
    try:
        # 1. Search page hit karna
        response = scraper.get(search_url, timeout=15)
        if response.status_code != 200:
            return None
            
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # 2. Pehli relevant movie post ka anchor tag dhoodna
        articles = soup.find_all('h3', class_='entry-title') or soup.find_all('h2', class_='entry-title')
        if not articles:
            return None
            
        target_page_url = None
        for article in articles:
            link_tag = article.find('a')
            if link_tag:
                post_title = link_tag.get_text().lower()
                # Confirm karna ke movie ka title match ho raha hai
                if movie_title.lower() in post_title:
                    target_page_url = link_tag['href']
                    break
                    
        if not target_page_url:
            # Agar specialized check miss ho to first block safety match backup par rakhna
            target_page_url = articles[0].find('a')['href']

        # 3. Target Movie Page open karna aur stream content nikalna
        movie_page_response = scraper.get(target_page_url, timeout=15)
        movie_soup = BeautifulSoup(movie_page_response.text, 'html.parser')
        
        # 4. Filter and catch direct servers links (Hubcloud/Pixeldrain/Vcloud etc.)
        final_stream_url = None
        for a_tag in movie_soup.find_all('a', href=True):
            href_url = a_tag['href']
            
            # Streaming aur high speed cloud links ko priority dena
            if "hubcloud" in href_url or "pixeldrain" in href_url or "vcloud" in href_url or "drive" in href_url:
                # Agar internal redirect server ho to usko safe player format dena
                if "hubcloud" in href_url and "drive" in href_url:
                    continue
                final_stream_url = href_url
                break # Pehla clean cloud server select hote hi loop close
                
        return final_stream_url

    except Exception as e:
        print(f"Scraper core error details: {str(e)}")
        return None

# App.js yahan hit karegi real-time link mangne ke liye
@app.route('/play', methods=['GET'])
def play_movie():
    tmdb_id = request.args.get('id')
    media_type = request.args.get('type')
    title = request.args.get('title')
    year = request.args.get('year', default='').split(',')[0].strip() # Clean base year format

    if not title:
        return jsonify({"status": "Error", "message": "Movie title parameter missing!"}), 400

    print(f"Request received to fetch links for: {title} ({year})")
    
    # Core function call to fetch direct sources
    live_link = scrape_hindi_links(title, year)

    if live_link:
        print(f"Success! Link Found: {live_link}")
        return jsonify({
            "status": "Success",
            "tmdb_id": tmdb_id,
            "media_type": media_type,
            "servers": {
                "name": "Dynamic Hindi Premium Stream",
                "url": live_link
            }
        })
    else:
        # Agar bot ko link na mile to error respond karna taaky app fallback local server auto load kare
        print("Hindi link not found on scraped networks, sending fallback signal.")
        return jsonify({
            "status": "Failed",
            "message": "No stream found on target sources"
        }), 404

if __name__ == '__main__':
    # Network hosting setup taaky mobile app connect kar sakay
    app.run(host='0.0.0.0', port=5000, debug=True)
