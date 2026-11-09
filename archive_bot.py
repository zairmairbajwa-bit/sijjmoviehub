import os
import time
import json
import asyncio
import re
import urllib.parse
from playwright.async_api import async_playwright
# Yahan import theek kar diya gaya hai
from playwright_stealth import stealth 
import requests
import subprocess
import internetarchive as ia
import shutil

# === APKI API KEYS ===
TMDB_API_KEY = "7b6a89d3dc55b3a81aa892a88c0da6b9"
FIREBASE_URL = "https://sijjmoviehub-default-rtdb.firebaseio.com"

# === BOT SETTINGS ===
BOT_ID = int(os.getenv("BOT_ID", "1"))
YEAR_START = int(os.getenv("YEAR_START", "2025"))
YEAR_END = int(os.getenv("YEAR_END", "2026"))
IA_ACCESS = os.getenv("IA_ACCESS", "").strip()
IA_SECRET = os.getenv("IA_SECRET", "").strip()

MAX_MOVIES_PER_RUN = 3
MIN_FILE_SIZE = 150 * 1024 * 1024  # 150 MB Minimum

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
        meta["category"] = "Popular Updates"
        requests.put(f"{FIREBASE_URL}/movies/{tmdb_id}.json", data=json.dumps(meta), timeout=15)
        return True
    return False

def download_with_aria2(url, work_dir):
    print(f"Downloading: {url}")
    cmd = [
        "aria2c", "--dir=" + work_dir, "--seed-time=0", "-x", "16", "-s", "16", "-j", "16", url
    ]
    try:
        subprocess.run(cmd, check=True, timeout=2400) # 40 Mins timeout per file
        for root, dirs, files in os.walk(work_dir):
            for file in files:
                if file.endswith((".mp4", ".mkv")):
                    return os.path.join(root, file)
    except:
        print(f"Aria2 download failed or timed out for {url}")
    return None

async def handle_new_page(page):
    """Ads aur naye tabs ko foran band karne ki logic"""
    print(f"Blocked pop-up ad tab.")
    await page.close()

async def search_and_extract_mp4moviez(page, movie_title):
    search_url = f"https://mp4moviez.computer/search.php?keyword={urllib.parse.quote(movie_title)}"
    print(f"Searching mp4moviez: {search_url}")
    await page.goto(search_url, timeout=60000)
    
    # Smart 18+ Captcha Bypass (YES, AGREE, ACCEPT, ENTER, OK)
    try:
        btn = page.locator("text=/(YES|AGREE|ACCEPT|ENTER|OK)/i").first
        if await btn.is_visible(timeout=5000):
            await btn.click()
            print("18+ Captcha bypassed successfully!")
            await page.wait_for_timeout(3000)
    except:
        pass 

    movie_links = {"url_480p": None, "url_720p": None, "url_1080p": None}
    
    try:
        links = await page.locator("a").all()
        target_movie_page = None
        for link in links:
            text = await link.inner_text()
            href = await link.get_attribute("href")
            
            if href and "movie" in href and movie_title.lower()[:5] in text.lower():
                target_movie_page = href
                break
        
        if not target_movie_page:
            print("Movie not found on mp4moviez.")
            return movie_links

        print(f"Movie page found: {target_movie_page}. Extracting resolution links...")
        await page.goto(target_movie_page, timeout=60000)
        
        all_download_links = await page.locator("a").all()
        for link in all_download_links:
            text = await link.inner_text()
            href = await link.get_attribute("href")
            
            if not href or not href.endswith(".mp4") or "Jio Users Only" in text:
                continue
                
            text = text.lower()
            if "480p" in text and not movie_links["url_480p"]:
                movie_links["url_480p"] = href
            elif "720p" in text and not movie_links["url_720p"]:
                movie_links["url_720p"] = href
            elif "1080p" in text and not movie_links["url_1080p"]:
                movie_links["url_1080p"] = href

    except Exception as e:
        print(f"Extraction error: {e}")
        
    print(f"Found Links: {movie_links}")
    return movie_links

async def run_bot():
    print(f"Starting SijjMoviesHub Mp4moviez Scraper Bot ID: {BOT_ID}")
    
    completed = 0
    start_time = time.time()
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=['--disable-blink-features=AutomationControlled'])
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        context.on("page", lambda page: asyncio.create_task(handle_new_page(page)))
        
        page = await context.new_page()
        # Yahan call theek kar di gayi hai
        await stealth(page)
        
        for p_num in range(BOT_ID, 50, 8):
            if completed >= MAX_MOVIES_PER_RUN: break
            if (time.time() - start_time) > 20000:
                print("Time limit reached.")
                break 

            tmdb_url = f"https://api.themoviedb.org/3/discover/movie?api_key={TMDB_API_KEY}&sort_by=popularity.desc&primary_release_date.gte={YEAR_START}-01-01&primary_release_date.lte={YEAR_END}-12-31&page={p_num}&with_original_language=hi"
            
            try:
                res = requests.get(tmdb_url, timeout=15).json()
                for m in res.get("results", []):
                    if completed >= MAX_MOVIES_PER_RUN: break
                    
                    tmdb_id = str(m.get("id"))
                    if is_already_in_firebase(tmdb_id): continue
                    
                    title = m.get("title", "Untitled")
                    print(f"\n--- Processing: {title} ---")
                    
                    extracted_links = await search_and_extract_mp4moviez(page, title)
                    
                    if any(extracted_links.values()):
                        wd = f"/tmp/w_{BOT_ID}_{tmdb_id}"
                        os.makedirs(wd, exist_ok=True)
                        
                        downloaded_paths = {}
                        for res_label, link in extracted_links.items():
                            if link:
                                path = download_with_aria2(link, wd)
                                if path: downloaded_paths[res_label] = path
                        
                        if any(downloaded_paths.values()):
                            meta = {
                                "tmdb_id": tmdb_id, "id": tmdb_id, "title": title, 
                                "overview": m.get("overview", ""), "release_date": m.get("release_date", ""), 
                                "poster": f"https://image.tmdb.org/t/p/w500{m.get('poster_path')}" if m.get('poster_path') else "", 
                                "hindi_dubbed": True 
                            }
                            if upload_to_archive_and_sync(meta, downloaded_paths):
                                completed += 1
                                print(f"Successfully fully synced {title} with multiple resolutions!")
                                
                        shutil.rmtree(wd, ignore_errors=True)
                    else:
                        print("Skipping... No direct mp4 links found on mp4moviez.")
            except Exception as e:
                print(f"Loop error: {e}")
                
        await browser.close()
    print("Bot run completed.")

if __name__ == "__main__":
    asyncio.run(run_bot())