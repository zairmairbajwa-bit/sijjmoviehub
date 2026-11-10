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
BASE_DOMAIN = "https://www.filmyzilla82.com"

BOT_ID = int(os.getenv("BOT_ID", "1"))
IA_ACCESS = os.getenv("IA_ACCESS", "").strip()
IA_SECRET = os.getenv("IA_SECRET", "").strip()

MAX_MOVIES_PER_RUN = 3
TOTAL_BOTS = 4

def clean_filename(name):
    return re.sub(r'[^a-zA-Z0-9_-]', '_', name)

def is_fully_in_firebase(tmdb_id):
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
    clean = re.sub(r'(?i)in HD Filmyzilla', '', clean)
    clean = re.sub(r'(?i)Filmyzilla', '', clean)
    clean = re.sub(r'(?i)(hindi dubbed|full movie|hdrip|bluray|web-dl|1080p|720p|480p).*', '', clean)
    clean = re.sub(r'\(\d{4}\)|\[\d{4}\]', '', clean)
    clean = re.sub(r'\(.*?\)|\[.*?\]', '', clean)
    clean = clean.replace('-', ' ').replace('_', ' ').strip()
    
    if not clean: return None
    if any(skip in clean.lower() for skip in ['latest', 'bengali', 'hollywood', 'bollywood', 'category', 'series']):
        return None
        
    print(f"[TMDB] Searching title on TMDB: '{clean}'")
    url = f"https://api.themoviedb.org/3/search/movie?api_key={TMDB_API_KEY}&query={urllib.parse.quote(clean)}&language=hi"
    try:
        res = requests.get(url, timeout=10).json()
        results = res.get("results", [])
        if results:
            print(f"[TMDB] Match Found! {results[0].get('title')} ({results[0].get('release_date')})")
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
        if vp and os.path.exists(vp):
            ext = os.path.splitext(vp)[1].lower()
            if ext not in [".mp4", ".mkv"]: ext = ".mp4" 
            cf = f"{clean_filename(meta['title'])}_{release_year}_{res_label}_{tmdb_id}{ext}"
            tp = os.path.join(os.path.dirname(vp), cf)
            if vp != tp:
                shutil.move(vp, tp)
            files_to_upload.append(tp)
            firebase_links[res_label] = f"https://archive.org/download/{ident}/{cf}"

    if not files_to_upload:
        return False

    print(f"Uploading files to Archive.org...")
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

def download_with_aria2(url, work_dir, referer_url):
    print(f"Downloading file via Aria2c...")
    cmd = [
        "aria2c", "--dir=" + work_dir, "--seed-time=0", "-x", "16", "-s", "16", "-j", "16", 
        "--content-disposition-default-utf8=true",
        f"--referer={referer_url}",
        "--header=User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        url
    ]
    try:
        subprocess.run(cmd, check=True, timeout=3600) 
        for root, dirs, files in os.walk(work_dir):
            for file in files:
                if file.lower().endswith((".mp4", ".mkv")) and not file.endswith(".aria2"):
                    return os.path.join(root, file)
    except Exception as e:
        print(f"Aria2 download failed: {e}")
    return None

async def run_bot():
    print(f"Starting Pure Human-Flow Bot ID: {BOT_ID}")
    completed = 0
    start_time = time.time()
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True, 
            args=['--disable-blink-features=AutomationControlled', '--no-sandbox', '--disable-dev-shm-usage']
        )
        context = await browser.new_context(
            accept_downloads=True,
            viewport={"width": 1366, "height": 768},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        
        def handle_popup(new_popup):
            asyncio.create_task(new_popup.close())
        context.on("page", handle_popup)
        
        page = await context.new_page()
        try:
            stealth = Stealth()
            await stealth.apply_stealth_async(page)
        except:
            pass

        # HUMAN STEP 1: Pehle website ka main page kholo taake Cloudflare clearance mil jaye
        print(f"Step 1: Opening Home Page -> {BASE_DOMAIN}")
        try:
            await page.goto(BASE_DOMAIN, timeout=60000, wait_until="domcontentloaded")
            await page.wait_for_timeout(4000) # Insano ki tarah thoda wait karo
        except Exception as e:
            print(f"Failed to open home page: {e}")
            await browser.close()
            return

        # Get all movie links directly from the opened front page
        all_movie_pages = []
        links = await page.locator("a").all()
        for link in links:
            href = await link.get_attribute("href")
            if href and "/movie/" in href and href.endswith(".html"):
                abs_url = urllib.parse.urljoin(BASE_DOMAIN, href)
                if abs_url not in all_movie_pages:
                    all_movie_pages.append(abs_url)

        # Bots mein hissay baant do
        chunk_size = max(1, len(all_movie_pages) // TOTAL_BOTS) if all_movie_pages else 1
        start_idx = (BOT_ID - 1) * chunk_size
        end_idx = start_idx + chunk_size if BOT_ID < TOTAL_BOTS else len(all_movie_pages)
        my_movie_pages = all_movie_pages[start_idx:end_idx] if all_movie_pages else []
        print(f"Bot {BOT_ID} assigned {len(my_movie_pages)} movies to download.")

        # HUMAN STEP 2: Bari bari movie ke naam par click karo
        for m_url in my_movie_pages:
            if completed >= MAX_MOVIES_PER_RUN: break
            if (time.time() - start_time) > 20000: break 

            print(f"\nStep 2: Clicking on Movie -> {m_url}")
            try:
                # Referer laga kar jana exactly link click karne ke barabar hai
                await page.goto(m_url, referer=BASE_DOMAIN, timeout=60000, wait_until="domcontentloaded")
                await page.wait_for_timeout(3000)
            except Exception as e:
                print(f"Skipped movie: {e}")
                continue
            
            raw_title = await page.title()
            tmdb_data = search_tmdb_from_title(raw_title)
            if not tmdb_data: continue
                
            tmdb_id = str(tmdb_data["id"])
            if is_fully_in_firebase(tmdb_id):
                print(f"Movie pehle se Firebase me hai. Next movie par ja rahe hain.")
                continue
            
            # Find 480p, 720p, 1080p links from the page
            res_links = {}
            for res_text in ["480p", "720p", "1080p"]:
                loc = page.locator(f"a:has-text('{res_text}')")
                if await loc.count() > 0:
                    href = await loc.first.get_attribute("href")
                    if href: res_links[res_text] = urllib.parse.urljoin(BASE_DOMAIN, href)

            if not res_links: continue

            wd = f"/tmp/filmy_{BOT_ID}_{tmdb_id}"
            os.makedirs(wd, exist_ok=True)
            downloaded_paths = {}

            # HUMAN STEP 3: Resolution par click karo (jesa k 720p)
            for res_label, resolution_page_url in res_links.items():
                print(f"Step 3: Clicking on Resolution {res_label}")
                try:
                    await page.goto(resolution_page_url, referer=m_url, timeout=60000, wait_until="domcontentloaded")
                    await page.wait_for_timeout(3000)
                    
                    # HUMAN STEP 4: Andar Server 4 ya 3 par click karo
                    server_url = None
                    s_anchors = await page.locator("a").all()
                    for sa in s_anchors:
                        s_text = await sa.inner_text()
                        if 'server 4' in s_text.lower():
                            server_url = urllib.parse.urljoin(page.url, await sa.get_attribute("href"))
                            break
                    if not server_url:
                        for sa in s_anchors:
                            s_text = await sa.inner_text()
                            if 'server 3' in s_text.lower():
                                server_url = urllib.parse.urljoin(page.url, await sa.get_attribute("href"))
                                break
                    
                    if server_url:
                        print(f"Step 4: Clicking on Server link to start download...")
                        async with page.expect_navigation(timeout=15000):
                            await page.goto(server_url, referer=resolution_page_url)
                        
                        direct_file_url = page.url
                        
                        f_path = download_with_aria2(direct_file_url, wd, resolution_page_url)
                        if f_path: downloaded_paths[res_label] = f_path
                        
                        # HUMAN STEP 5: Download ke baad back aao
                        print(f"Step 5: Going BACK to the previous page...")
                        await page.go_back(wait_until="domcontentloaded")
                        await page.wait_for_timeout(2000)
                        
                except Exception as e:
                    print(f"Failed download step for {res_label}: {e}")

            # Jab teeno resolution ho jayein, toh sync kar do
            if downloaded_paths:
                title = tmdb_data.get("title", "Untitled")
                meta = {
                    "tmdb_id": tmdb_id, "id": tmdb_id, "title": title, 
                    "overview": tmdb_data.get("overview", ""), "release_date": tmdb_data.get("release_date", ""), 
                    "poster": f"https://image.tmdb.org/t/p/w500{tmdb_data.get('poster_path')}" if tmdb_data.get('poster_path') else "", 
                    "hindi_dubbed": True 
                }
                if upload_to_archive_and_sync(meta, downloaded_paths):
                    completed += 1
                    print(f"Movie Uploaded Successfully!")
                    
            shutil.rmtree(wd, ignore_errors=True)
            
            # Wapis front page par jao agli movie ke liye
            await page.goto(BASE_DOMAIN, timeout=60000, wait_until="domcontentloaded")
            await page.wait_for_timeout(2000)
                
        await browser.close()
    print("Bot run completed.")

if __name__ == "__main__":
    asyncio.run(run_bot())
