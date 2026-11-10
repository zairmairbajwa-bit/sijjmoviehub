import os
import time
import json
import asyncio
import re
import random
import urllib.parse
import base64
from playwright.async_api import async_playwright
from playwright_stealth import Stealth 
import requests
import subprocess
import internetarchive as ia
import shutil

# AI Vision ke liye
from PIL import Image
import pytesseract

# === SECURE CREDENTIALS ===
TMDB_API_KEY = os.getenv("TMDB_API_KEY", "7b6a89d3dc55b3a81aa892a88c0da6b9")
FIREBASE_URL = os.getenv("FIREBASE_URL", "https://sijjmoviehub-default-rtdb.firebaseio.com")
BASE_DOMAIN = "https://www.mp4moviez.computer"

# Aapki Direct API Key
OCR_API_KEY = "K8787437980056088957"

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
    if any(skip in clean.lower() for skip in ['latest', 'bengali', 'hollywood', 'bollywood', 'category', 'series']):
        return None
        
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
        break 
            
    real_movies = [u for u in all_movie_urls if u != start_url and not "latest-hollywood" in u]
    return list(set(real_movies))

# 🤖 HUMAN-LIKE HUMAN CLICK WITH DOUBLE TAP
async def human_click(page, locator):
    try:
        await locator.scroll_into_view_if_needed()
        await page.wait_for_timeout(random.randint(500, 1000))
        box = await locator.bounding_box()
        if box:
            x = box['x'] + (box['width'] / 2) + random.uniform(-5, 5)
            y = box['y'] + (box['height'] / 2) + random.uniform(-2, 2)
            
            await page.mouse.move(x, y, steps=10)
            await page.mouse.down()
            await page.wait_for_timeout(50)
            await page.mouse.up()
            
            await page.wait_for_timeout(600)
            
            await page.mouse.down()
            await page.wait_for_timeout(50)
            await page.mouse.up()
            print("👤 Double-tap click executed successfully.")
        else:
            await locator.click(force=True)
    except Exception as e:
        await locator.click(force=True)

# ==========================================
# 🚀 ONLINE AI API CAPTCHA SOLVER
# ==========================================
def solve_captcha_api(img_bytes):
    try:
        if not OCR_API_KEY: return None
        base64_img = "data:image/png;base64," + base64.b64encode(img_bytes).decode('utf-8')
        
        payload = {
            'apikey': OCR_API_KEY,
            'base64Image': base64_img,
            'OCREngine': '2',
            'scale': 'true'
        }
        res = requests.post('https://api.ocr.space/parse/image', data=payload, timeout=15)
        result = res.json()
        
        if "ParsedResults" in result and len(result["ParsedResults"]) > 0:
            parsed_text = result["ParsedResults"][0].get("ParsedText", "")
            num = "".join(filter(str.isdigit, parsed_text))
            return num
    except:
        pass
    return None

async def try_solve_captcha_and_extract(target_page):
    try:
        if target_page.is_closed(): return None
        
        # 1. Check if direct download or media link is visible on current page/popup
        all_anchors = await target_page.locator("a").all()
        for a in all_anchors:
            try:
                href = await a.get_attribute("href")
                txt = await a.inner_text()
                if href:
                    href_lower = href.lower()
                    txt_lower = txt.lower() if txt else ""
                    if any(skip in txt_lower for skip in ['new hollywood series', 'category', 'home', 'disclaimer']): continue
                    
                    if any(href_lower.endswith(ext) for ext in ['.mp4', '.mkv']) or 'download' in href_lower or 'server' in href_lower or 'click here' in txt_lower:
                        abs_link = urllib.parse.urljoin(target_page.url, href)
                        if not any(bad in abs_link.lower() for bad in ['javascript', '#', 'contact', 'disclaimer']):
                            print(f"🎯 [EXTRACTOR] Found direct download target link: {abs_link}")
                            return abs_link
            except:
                continue

        # 2. Check if Captcha is active
        for frame in target_page.frames:
            try:
                url_lower = frame.url.lower()
                if any(x in url_lower for x in ['auralogicpine', 'filter', 'captcha', 'verify', 'challenge']):
                    input_loc = frame.locator("input[type='text']").first
                    btn_loc = frame.locator("input[type='submit'], button, input[value='Continue']").first
                    if await input_loc.count() > 0 and await btn_loc.count() > 0 and await input_loc.is_visible():
                        all_imgs = await frame.locator("img").all()
                        for img_loc in all_imgs:
                            box = await img_loc.bounding_box()
                            if box and box['width'] > 30 and box['height'] > 15 and box['height'] < 250:
                                img_bytes = await img_loc.screenshot()
                                num = solve_captcha_api(img_bytes)
                                if num and len(num) >= 3:
                                    await input_loc.fill(num)
                                    await target_page.wait_for_timeout(300)
                                    await btn_loc.click()
                                    await target_page.wait_for_timeout(4000)
                                    return None
            except:
                continue
    except:
        pass
    return None

async def run_bot():
    print(f"Starting SijjMoviesHub Direct Extraction Bot ID: {BOT_ID}")
    
    BOT_DIRECT_URLS = {
        1: "https://www.mp4moviez.computer/359/latest-hollywood-hindi-dubbed-movies-(2026).html",
        2: "https://www.mp4moviez.computer/333/latest-hollywood-hindi-dubbed-movies-(2025).html",
        3: "https://www.mp4moviez.computer/289/latest-hollywood-hindi-dubbed-movies-(2024).html",
        4: "https://www.mp4moviez.computer/235/latest-hollywood-hindi-dubbed-movies-(2023).html"
    }
    
    target_url = BOT_DIRECT_URLS.get(BOT_ID, BOT_DIRECT_URLS[1])
    completed = 0
    start_time = time.time()
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=['--disable-blink-features=AutomationControlled'])
        context = await browser.new_context(
            accept_downloads=True,
            viewport={"width": 1366, "height": 768},
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
                await page.wait_for_timeout(3000)
            except:
                continue
            
            raw_title = await page.title()
            tmdb_data = search_tmdb_from_title(raw_title)
            if not tmdb_data: continue
                
            tmdb_id = str(tmdb_data["id"])
            if is_already_in_firebase(tmdb_id): continue
            
            all_links = await page.locator("a").all()
            target_link = None
            res_label = None
            
            for link in all_links:
                try:
                    text = await link.inner_text()
                    href = await link.get_attribute("href")
                except:
                    continue
                    
                if not href or href == "#": continue
                text_lower = text.lower() if text else ""
                if "jio users" in text_lower or "low quality" in text_lower: continue
                    
                if any(res in text_lower for res in ['.mp4', '.mkv', '720', '480']):
                    if any(nav in text_lower for nav in ['home', 'category', 'disclaimer', 'contact', 'series']): continue
                        
                    if "720" in text_lower or "pc hd" in text_lower:
                        target_link = link; res_label = "url_720p"; break
                    elif "480" in text_lower:
                        if not res_label: target_link = link; res_label = "url_480p"

            if not target_link: continue
                
            wd = f"/tmp/w_{BOT_ID}_{tmdb_id}"
            os.makedirs(wd, exist_ok=True)
            downloaded_paths = {}

            # Network sniffer as backup
            stolen_media_url = None
            async def sniff_response(response):
                nonlocal stolen_media_url
                if stolen_media_url: return
                try:
                    url = response.url.lower()
                    if any(bad in url for bad in ['cdn-cgi', 'analytics', 'pixel', 'stat']): return
                    ct = response.headers.get("content-type", "").lower()
                    if "video/" in ct or "application/octet-stream" in ct or "application/x-download" in ct:
                        stolen_media_url = response.url
                        print(f"🕵️ [SNIFFER] Media caught: {response.url}")
                    elif '?'.split(url)[0].endswith(('.mp4', '.mkv', '.avi', '.mov')):
                        stolen_media_url = response.url
                        print(f"🕵️ [SNIFFER] Media caught (Clean): {response.url}")
                except:
                    pass

            context.on("response", sniff_response)
            
            popups = []
            def handle_new_tab(new_page):
                popups.append(new_page)
            context.on("page", handle_new_tab)

            print(f"Clicking link for {res_label} and extracting redirect/download URL...")
            await human_click(page, target_link)
            
            extracted_url = None
            for _ in range(45):
                if stolen_media_url or extracted_url: break
                
                # Check main page
                res = await try_solve_captcha_and_extract(page)
                if res:
                    extracted_url = res
                    break
                    
                # Check popups
                for p in popups:
                    if not p.is_closed():
                        res = await try_solve_captcha_and_extract(p)
                        if res:
                            extracted_url = res
                            break
                await asyncio.sleep(1)

            context.remove_listener("response", sniff_response)
            context.remove_listener("page", handle_new_tab)
            for p in popups:
                try: await p.close()
                except: pass

            final_url = stolen_media_url or extracted_url
            if final_url:
                print(f"🎯 Handing over link to Aria2c: {final_url}")
                path = download_with_aria2(final_url, wd, m_url)
                if path:
                    downloaded_paths[res_label] = path
            else:
                print("❌ Failed to capture final download link.")

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
