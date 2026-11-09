import os
import time
import json
import asyncio
import re
import urllib.parse
from playwright.async_api import async_playwright
from playwright_stealth import Stealth 
import requests
import subprocess
import internetarchive as ia
import shutil

# === APKI API KEYS ===
TMDB_API_KEY = "7b6a89d3dc55b3a81aa892a88c0da6b9"
FIREBASE_URL = "https://sijjmoviehub-default-rtdb.firebaseio.com"
BASE_DOMAIN = "https://mp4moviez.computer"

# === BOT SETTINGS ===
BOT_ID = int(os.getenv("BOT_ID", "1"))
IA_ACCESS = os.getenv("IA_ACCESS", "").strip()
IA_SECRET = os.getenv("IA_SECRET", "").strip()

MAX_MOVIES_PER_RUN = 5

def clean_filename(name):
    return re.sub(r'[^a-zA-Z0-9_-]', '_', name)

def is_already_in_firebase(tmdb_id):
    try:
        res = requests.get(f"{FIREBASE_URL}/movies/{tmdb_id}.json", timeout=10)
        if res.status_code == 200 and res.json():
            data = res.json()
            if "archive.org/download/" in data.get("url_720p", "") or "archive.org/download/" in data.get("stream_url", ""):
                return True
    except:
        pass
    return False

def search_tmdb_from_title(raw_title):
    clean = re.sub(r'\(.*?\)|\[.*?\]', '', raw_title)
    clean = re.sub(r'(?i)(hindi dubbed|full movie|download|mp4moviez|hdrip|bluray|web-dl|1080p|720p|480p|movies|series|season|episode|ep).*', '', clean)
    clean = clean.replace('-', ' ').replace('_', ' ').strip()
    
    if not clean: return None
    print(f"[TMDB] Searching clean title on TMDB: '{clean}'")
    
    url = f"https://api.themoviedb.org/3/search/movie?api_key={TMDB_API_KEY}&query={urllib.parse.quote(clean)}&language=hi"
    try:
        res = requests.get(url, timeout=10).json()
        results = res.get("results", [])
        if results:
            print(f"[TMDB] Match Found! Official Name: {results[0].get('title')} ({results[0].get('release_date')})")
            return results[0]
    except Exception as e:
        print(f"TMDB Error: {e}")
    return None

def upload_to_archive_and_sync(meta, video_paths):
    tmdb_id = str(meta["id"])
    release_year = meta.get("release_date", "2026")[:4]
    ident = f"sijjhub-media-{tmdb_id}-{int(time.time())}"
    
    files_to_upload = []
    firebase_links = {}
    
    for res_label, vp in video_paths.items():
        if vp:
            ext = os.path.splitext(vp)[1].lower()
            cf = f"{clean_filename(meta['title'])}_{release_year}_{res_label}_{tmdb_id}{ext}"
            tp = os.path.join(os.path.dirname(vp), cf)
            os.rename(vp, tp)
            files_to_upload.append(tp)
            firebase_links[res_label] = f"https://archive.org/download/{ident}/{cf}"

    if not files_to_upload:
        return False

    print(f"Uploading {len(files_to_upload)} files to Archive.org...")
    r = ia.upload(
        ident, 
        files=files_to_upload, 
        metadata={"title": f"{meta['title']} ({release_year})", "mediatype": "movies"}, 
        access_key=IA_ACCESS, 
        secret_key=IA_SECRET
    )
    
    if r and r[0].status_code == 200:
        meta.update(firebase_links)
        meta["stream_url"] = firebase_links.get("url_720p") or firebase_links.get("url_480p") or firebase_links.get("url_1080p")
        meta["category"] = "Latest Updates"
        requests.put(f"{FIREBASE_URL}/movies/{tmdb_id}.json", data=json.dumps(meta), timeout=15)
        return True
    return False

def download_with_aria2(url, work_dir):
    print(f"Downloading: {url}")
    cmd = [
        "aria2c", "--dir=" + work_dir, "--seed-time=0", "-x", "16", "-s", "16", "-j", "16", url
    ]
    try:
        subprocess.run(cmd, check=True, timeout=2400) 
        for root, dirs, files in os.walk(work_dir):
            for file in files:
                if file.endswith((".mp4", ".mkv", ".zip", ".rar")):
                    return os.path.join(root, file)
    except:
        print(f"Aria2 download failed for {url}")
    return None

async def handle_new_page(popup):
    try:
        print(f"Blocked pop-up ad tab.")
        await popup.close()
    except:
        pass

async def get_year_folders(page, category_url):
    print(f"Scanning Category for Year Folders: {category_url}")
    await page.goto(category_url, timeout=60000)
    
    try:
        btn = page.locator("text=/(YES|AGREE|ACCEPT|ENTER|OK)/i").first
        if await btn.is_visible(timeout=5000):
            await btn.click()
            await page.wait_for_timeout(3000)
    except:
        pass 
        
    links = await page.locator("a").all()
    year_folders = []
    
    for link in links:
        text = await link.inner_text()
        href = await link.get_attribute("href")
        
        if href and text and re.search(r'\b(2026|2025|2024|2023)\b', text):
            abs_url = urllib.parse.urljoin(BASE_DOMAIN, href)
            if abs_url not in year_folders:
                year_folders.append(abs_url)
                
    year_folders = sorted(year_folders, reverse=True) # Newest year first (2026...)
    return year_folders

async def get_paginated_movies(page, year_url):
    """Year folder ke saare pages scan kar ke sirf ASALI movies nikalna (Menu/Category ignore)"""
    current_url = year_url
    all_movie_urls = []
    
    # Menu aur Category wale kachra words ki strict blacklist
    bad_keywords = [
        'category', 'movies.html', 'series.html', 'tagalog', 'bhojpuri', 
        'gujarati', 'marathi', 'wwe', 'south-indian', 'punjabi-movies', 
        'bollywood-movies', 'hollywood-movies', 'tv-series', 'web-series',
        'bengali', 'pakistani', 'telugu', 'tamil'
    ]
    
    while current_url:
        print(f"Scanning Year Page: {current_url}")
        await page.goto(current_url, timeout=60000)
        
        links = await page.locator("a").all()
        page_movies = []
        next_page_url = None
        
        for link in links:
            text = await link.inner_text()
            href = await link.get_attribute("href")
            
            if href:
                abs_url = urllib.parse.urljoin(BASE_DOMAIN, href)
                filename = abs_url.split('/')[-1].lower()
                
                # Check agar yeh koi category ya menu link hai
                is_category = any(bad in filename for bad in bad_keywords)
                
                # Sirf wohi link jo Asali Movie ka ho (ID folder ho + .html ho + category na ho)
                if abs_url.endswith(".html") and re.search(r'/\d+/[^/]+\.html$', abs_url) and not is_category:
                    if abs_url not in all_movie_urls and abs_url not in page_movies:
                        page_movies.append(abs_url)
                
                # Next page link check
                text_lower = text.lower() if text else ""
                if "next" in text_lower or ">" in text_lower or ">>" in text_lower:
                    if not next_page_url and ("category" in abs_url or "page" in abs_url):
                        next_page_url = abs_url

        all_movie_urls.extend(page_movies)
        
        if next_page_url and next_page_url != current_url:
            current_url = next_page_url
        else:
            break
            
    return all_movie_urls

async def run_bot():
    print(f"Starting SijjMoviesHub Strict Filter Bot ID: {BOT_ID}")
    
    TARGET_CATEGORIES = {
        1: "https://mp4moviez.computer/category/latest-hollywood-hindi-dubbed-movies.html",
        2: "https://mp4moviez.computer/category/latest-bollywood-movies.html",
        3: "https://mp4moviez.computer/category/punjabi-movies.html",
        4: "https://mp4moviez.computer/category/latest-hollywood-hindi-dubbed-movies.html"
    }
    
    my_category = TARGET_CATEGORIES.get(BOT_ID, TARGET_CATEGORIES[1])
    
    completed = 0
    start_time = time.time()
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=['--disable-blink-features=AutomationControlled'])
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        
        page = await context.new_page()
        page.on("popup", lambda popup: asyncio.create_task(handle_new_page(popup)))
        await Stealth().apply_stealth_async(page)
        
        year_folders = await get_year_folders(page, my_category)
        print(f"Found {len(year_folders)} Year Folders: {year_folders}")
        
        for y_url in year_folders:
            if completed >= MAX_MOVIES_PER_RUN: break
            if (time.time() - start_time) > 20000: break
            
            movie_pages = await get_paginated_movies(page, y_url)
            print(f"Total REAL movies found across pages in this year folder: {len(movie_pages)}")
            
            for m_url in movie_pages:
                if completed >= MAX_MOVIES_PER_RUN: break
                if (time.time() - start_time) > 20000: break 

                print(f"\n--- Opening Movie/Series Page: {m_url} ---")
                await page.goto(m_url, timeout=60000)
                
                raw_title = await page.title()
                
                tmdb_data = search_tmdb_from_title(raw_title)
                if not tmdb_data:
                    print("Could not match with TMDB. Skipping...")
                    continue
                    
                tmdb_id = str(tmdb_data["id"])
                if is_already_in_firebase(tmdb_id):
                    print(f"Movie {tmdb_id} is already in Firebase. Skipping...")
                    continue
                
                movie_links = {"url_480p": None, "url_720p": None, "url_1080p": None}
                all_download_links = await page.locator("a").all()
                
                for link in all_download_links:
                    text = await link.inner_text()
                    href = await link.get_attribute("href")
                    
                    if not href:
                        continue
                        
                    text_lower = text.lower() if text else ""
                    
                    if "jio users only" in text_lower or "pc users" in text_lower:
                        continue
                        
                    href = urllib.parse.urljoin(BASE_DOMAIN, href)
                    
                    if not href.lower().endswith((".mp4", ".mkv", ".zip", ".rar")):
                        continue
                        
                    if "480p" in text_lower and not movie_links["url_480p"]: 
                        movie_links["url_480p"] = href
                    elif "720p" in text_lower and not movie_links["url_720p"]: 
                        movie_links["url_720p"] = href
                    elif ("1080p" in text_lower or "full hd" in text_lower) and not movie_links["url_1080p"]: 
                        movie_links["url_1080p"] = href

                if any(movie_links.values()):
                    wd = f"/tmp/w_{BOT_ID}_{tmdb_id}"
                    os.makedirs(wd, exist_ok=True)
                    
                    downloaded_paths = {}
                    for res_label, dl_link in movie_links.items():
                        if dl_link:
                            path = download_with_aria2(dl_link, wd)
                            if path: downloaded_paths[res_label] = path
                    
                    if any(downloaded_paths.values()):
                        title = tmdb_data.get("title", "Untitled")
                        meta = {
                            "tmdb_id": tmdb_id, "id": tmdb_id, "title": title, 
                            "overview": tmdb_data.get("overview", ""), "release_date": tmdb_data.get("release_date", ""), 
                            "poster": f"https://image.tmdb.org/t/p/w500{tmdb_data.get('poster_path')}" if tmdb_data.get('poster_path') else "", 
                            "hindi_dubbed": True 
                        }
                        if upload_to_archive_and_sync(meta, downloaded_paths):
                            completed += 1
                            print(f"Successfully synced {title} with multiple resolutions!")
                            
                    shutil.rmtree(wd, ignore_errors=True)
                else:
                    print("No suitable download links found on this page.")
                    
        await browser.close()
    print("Bot run completed.")

if __name__ == "__main__":
    asyncio.run(run_bot())