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

# === SECURE CREDENTIALS ===
TMDB_API_KEY = os.getenv("TMDB_API_KEY", "7b6a89d3dc55b3a81aa892a88c0da6b9")
FIREBASE_URL = os.getenv("FIREBASE_URL", "https://sijjmoviehub-default-rtdb.firebaseio.com")
BASE_DOMAIN = "https://www.mp4moviez.computer"

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
            if data.get("url_720p") and data.get("url_480p") and data.get("url_1080p"):
                return True
    except:
        pass
    return False

def search_tmdb_from_title(raw_title):
    clean = raw_title
    clean = re.sub(r'(?i)\bDownload\b', '', clean)
    clean = re.sub(r'(?i)in HD Mp4moviez', '', clean)
    clean = re.sub(r'(?i)Mp4moviez', '', clean)
    clean = re.sub(r'(?i)(hindi dubbed|full movie|hdrip|bluray|web-dl|1080p|720p|480p).*', '', clean)
    clean = re.sub(r'\(\d{4}\)|\[\d{4}\]', '', clean)
    clean = re.sub(r'\(.*?\)|\[.*?\]', '', clean)
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
            if ext not in [".mp4", ".mkv"]: ext = ".mp4" 
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

# FAST DOWNLOADER (Aria2c)
def download_with_aria2(url, work_dir, referer_url):
    print(f"Starting Aria2c Fast Download: {url}")
    cmd = [
        "aria2c", "--dir=" + work_dir, "--seed-time=0", "-x", "16", "-s", "16", "-j", "16", 
        "--content-disposition-default-utf8=true",
        f"--referer={referer_url}",
        "--header=User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        url
    ]
    try:
        subprocess.run(cmd, check=True, timeout=2400) 
        for root, dirs, files in os.walk(work_dir):
            for file in files:
                if file.lower().endswith((".mp4", ".mkv")):
                    return os.path.join(root, file)
                elif not file.endswith(".aria2") and not file.lower().endswith(".html"):
                    return os.path.join(root, file)
    except Exception as e:
        print(f"Aria2 download failed: {e}")
    return None

async def get_paginated_movies(page, start_url):
    current_url = start_url
    all_movie_urls = []
    
    while current_url:
        print(f"Scanning Page: {current_url}")
        try:
            await page.goto(current_url, timeout=60000)
            await page.wait_for_timeout(2000)
        except Exception as e:
            break
        
        links = await page.locator("a").all()
        page_movies = []
        
        for link in links:
            try:
                href = await link.get_attribute("href")
            except:
                continue
                
            if href:
                abs_url = urllib.parse.urljoin(BASE_DOMAIN, href)
                path_lower = abs_url.lower()
                
                if abs_url.endswith(".html") and re.search(r'/[a-z0-9]+/[^/]+\.html$', abs_url, re.IGNORECASE):
                    if not any(skip in path_lower for skip in ['category', 'disclaimer', 'report', 'index', 'home', 'contact']):
                        if abs_url not in all_movie_urls and abs_url not in page_movies:
                            page_movies.append(abs_url)

        all_movie_urls.extend(page_movies)
        print(f"Total links gathered so far: {len(all_movie_urls)}")
        break 
            
    real_movies = [u for u in all_movie_urls if u != start_url and not "latest-hollywood" in u]
    return list(set(real_movies))

async def run_bot():
    print(f"Starting SijjMoviesHub Direct URL Bot ID: {BOT_ID}")
    
    BOT_DIRECT_URLS = {
        1: "https://www.mp4moviez.computer/359/latest-hollywood-hindi-dubbed-movies-(2026).html",
        2: "https://www.mp4moviez.computer/333/latest-hollywood-hindi-dubbed-movies-(2025).html",
        3: "https://www.mp4moviez.computer/289/latest-hollywood-hindi-dubbed-movies-(2024).html",
        4: "https://www.mp4moviez.computer/235/latest-hollywood-hindi-dubbed-movies-(2023).html"
    }
    
    target_url = BOT_DIRECT_URLS.get(BOT_ID, BOT_DIRECT_URLS[1])
    print(f"Bot {BOT_ID} Target URL: {target_url}")
    
    completed = 0
    start_time = time.time()
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=['--disable-blink-features=AutomationControlled'])
        context = await browser.new_context(
            accept_downloads=True,
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        
        page = await context.new_page()
        await Stealth().apply_stealth_async(page)
        
        movie_pages = await get_paginated_movies(page, target_url)
        print(f"Total REAL movies found: {len(movie_pages)}")
        
        for m_url in movie_pages:
            if completed >= MAX_MOVIES_PER_RUN: break
            if (time.time() - start_time) > 20000: break 

            print(f"\n--- Opening Movie Page: {m_url} ---")
            try:
                await page.goto(m_url, timeout=60000)
                await page.wait_for_timeout(2000)
            except:
                continue
            
            raw_title = await page.title()
            
            tmdb_data = search_tmdb_from_title(raw_title)
            if not tmdb_data:
                print("Could not match with TMDB. Skipping...")
                continue
                
            tmdb_id = str(tmdb_data["id"])
            if is_already_in_firebase(tmdb_id):
                print(f"Movie {tmdb_id} is already in Firebase. Skipping...")
                continue
            
            all_links = await page.locator("a").all()
            target_link = None
            res_label = None
            
            for link in all_links:
                try:
                    text = await link.inner_text()
                    href = await link.get_attribute("href")
                except:
                    continue
                    
                if not href or href == "#": 
                    continue
                
                text_lower = text.lower() if text else ""
                
                if "jio users" in text_lower or "low quality" in text_lower:
                    continue
                    
                if any(res in text_lower for res in ['.mp4', '.mkv', '1080', '720', '480', 'pc hd']):
                    if any(nav in text_lower for nav in ['home', 'category', 'disclaimer', 'contact']):
                        continue
                        
                    if "1080" in text_lower or "full hd" in text_lower:
                        target_link = link
                        res_label = "url_1080p"
                        break
                    elif "720" in text_lower or "pc hd" in text_lower:
                        if res_label != "url_1080p":
                            target_link = link
                            res_label = "url_720p"
                    elif "480" in text_lower:
                        if not res_label:
                            target_link = link
                            res_label = "url_480p"

            if not target_link:
                print("No suitable download link found on this page.")
                continue
                
            wd = f"/tmp/w_{BOT_ID}_{tmdb_id}"
            os.makedirs(wd, exist_ok=True)
            downloaded_paths = {}

            # ==========================================
            # 🕵️ STRICT CLOUDFLARE-FILTERED SNIFFER
            # ==========================================
            stolen_media_url = None
            
            async def sniff_response(response):
                nonlocal stolen_media_url
                if stolen_media_url: return
                
                try:
                    url = response.url.lower()
                    
                    # 🚫 CLOUDFLARE & ANALYTICS SCRIPTS BLOCKER
                    if any(bad in url for bad in ['cdn-cgi', 'rum', 'analytics', 'googletagmanager', 'pixel', 'stat']):
                        return

                    headers = response.headers
                    content_type = headers.get("content-type", "").lower()
                    
                    # Ignore HTML, JS, CSS, Images
                    if any(ext in url for ext in ['.html', '.js', '.css']) or 'text/html' in content_type or 'image/' in content_type:
                        return

                    # Check Content-Type for actual video or binary download stream
                    if "video/" in content_type or "application/octet-stream" in content_type or "application/x-download" in content_type:
                        stolen_media_url = response.url
                        print(f"🕵️ [SNIFFER] Asli media link chura liya (Type: {content_type}): {response.url}")
                        
                    # Strict URL check (Must end with real extension before query params)
                    elif ('?'.split(url)[0].endswith('.mp4') or '?'.split(url)[0].endswith('.mkv')):
                        stolen_media_url = response.url
                        print(f"🕵️ [SNIFFER] Asli media link chura liya (Clean Extension): {response.url}")
                except Exception:
                    pass

            context.on("response", sniff_response)
            
            popups = []
            def handle_new_tab(new_page):
                popups.append(new_page)
            context.on("page", handle_new_tab)

            print(f"Clicking button for {res_label} and waiting for Filtered Sniffer...")
            try:
                await target_link.click(force=True)
                
                # Wait up to 25 seconds for the actual media response
                for _ in range(25):
                    if stolen_media_url:
                        break
                    await asyncio.sleep(1)
                    
            except Exception as e:
                print(f"Error clicking link: {e}")

            # Cleanup listeners
            context.remove_listener("response", sniff_response)
            context.remove_listener("page", handle_new_tab)
            for p in popups:
                try: await p.close()
                except: pass

            # ==========================================
            # 🚀 DIRECT DOWNLOADING VIA ARIA2C
            # ==========================================
            if stolen_media_url:
                print(f"🎯 Sniffer Success! Handing over pure link to Aria2c...")
                path = download_with_aria2(stolen_media_url, wd, m_url)
                if path:
                    downloaded_paths[res_label] = path
                    print(f"Download complete via Aria2c: {path}")
            else:
                print("❌ Sniffer failed to catch the media link.")

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
                    print(f"Successfully synced {title}!")
                    
            shutil.rmtree(wd, ignore_errors=True)
                
        await browser.close()
    print("Bot run completed.")

if __name__ == "__main__":
    asyncio.run(run_bot())
