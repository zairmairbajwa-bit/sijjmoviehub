import os
import time
import json
import re
import urllib.parse
import requests
import subprocess
import internetarchive as ia
import shutil
import random

# === SECURE CREDENTIALS ===
TMDB_API_KEY = os.getenv("TMDB_API_KEY", "").strip() or "7b6a89d3dc55b3a81aa892a88c0da6b9"
FIREBASE_URL = os.getenv("FIREBASE_URL", "").strip() or "https://sijjmoviehub-default-rtdb.firebaseio.com"
BASE_DOMAIN = "https://filmicity.in" # Naya working domain!

BOT_ID = int(os.getenv("BOT_ID", "1") or "1")
TOTAL_BOTS = 8

actual_bot_account_id = ((BOT_ID - 1) % 4) + 1
IA_ACCESS = os.getenv(f"IA_ACCESS_{actual_bot_account_id}", "").strip()
IA_SECRET = os.getenv(f"IA_SECRET_{actual_bot_account_id}", "").strip()

MAX_MOVIES_PER_RUN = 15

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Referer": BASE_DOMAIN
})

def clean_filename(name):
    cleaned = re.sub(r'[^a-zA-Z0-9_-]', '_', name)
    return re.sub(r'_+', '_', cleaned).strip('_')

def get_firebase_movie_data(tmdb_id):
    try:
        res = requests.get(f"{FIREBASE_URL}/movies/{tmdb_id}.json", timeout=10)
        if res.status_code == 200 and res.json():
            return res.json()
    except: pass
    return None

def clean_title_for_tmdb(raw_title):
    clean = re.sub(r'(?i)\bDownload\b', '', raw_title)
    clean = re.sub(r'(?i)in HD Filmyzilla.*', '', clean)
    clean = re.sub(r'(?i)Filmyzilla', '', clean)
    clean = re.sub(r'(?i)Hindi Dubbed.*', '', clean)
    clean = re.sub(r'(?i)(full movie|hdrip|bluray|web-dl|1080p|720p|480p).*', '', clean)
    clean = re.sub(r'\(\d{4}\)|\[\d{4}\]', '', clean)
    clean = re.sub(r'\(.*?\)|\[.*?\]', '', clean)
    return clean.replace('-', ' ').replace('_', ' ').strip()

# 💡 PERFECTED DEEP SPIDER CRAWLER
def crawl_filmyzilla_deep_categories(bot_id):
    print(f"🕸️ [BOT {bot_id}] Initiating DEEP SPIDER CRAWL on {BASE_DOMAIN} Categories & Years...")
    
    try:
        r = session.get(BASE_DOMAIN, timeout=15)
    except Exception as e:
        print(f"❌ Initial connect failed: {e}")
        return []
        
    category_urls = []
    
    matches = re.finditer(r'<a\s+[^>]*href=["\']([^"\']+)["\'][^>]*>', r.text, re.IGNORECASE)
    for match in matches:
        href = match.group(1)
        full_url = urllib.parse.urljoin(BASE_DOMAIN, href)
        
        # Har category ko list mein daalo
        if full_url.startswith(BASE_DOMAIN) and "/category/" in full_url.lower():
            if full_url not in category_urls:
                category_urls.append(full_url)
                    
    category_urls = sorted(list(set(category_urls)))
    
    # 💡 STRICT BOT DIVISION 
    my_categories = category_urls[(bot_id - 1) :: TOTAL_BOTS]
    print(f"📁 [BOT {bot_id}] Assigned {len(my_categories)} Main Category Folders.")
    
    all_movie_links = set()
    visited_pages = set()
    
    for cat_url in my_categories:
        print(f"\n🕷️ [BOT {bot_id}] Entering Main Folder: {cat_url}")
        to_visit = [cat_url]
        pages_crawled = 0
        
        while to_visit and pages_crawled < 25: 
            current_url = to_visit.pop(0)
            if current_url in visited_pages: continue
            visited_pages.add(current_url)
            pages_crawled += 1
            
            print(f"  -> 🔍 Scanning: {current_url}")
            
            try:
                resp = session.get(current_url, timeout=15)
                sub_matches = re.finditer(r'<a\s+[^>]*href=["\']([^"\']+)["\'][^>]*>', resp.text, re.IGNORECASE)
                
                for match in sub_matches:
                    shref = match.group(1)
                    sfull = urllib.parse.urljoin(BASE_DOMAIN, shref)
                    
                    if not sfull.startswith(BASE_DOMAIN): continue
                    
                    # Agar link mein /movie/ hai ya direct HTML page hai (without category/default)
                    if "/movie/" in sfull.lower() or (sfull.endswith(".html") and "/category/" not in sfull.lower() and "/default/" not in sfull.lower()):
                        all_movie_links.add(sfull)
                        
                    # Agar yeh aagay mazeed koi folder/year hai
                    elif "/category/" in sfull.lower() or "/default/" in sfull.lower():
                        if sfull not in visited_pages and sfull not in to_visit:
                            to_visit.append(sfull)
            except: pass
            
    sorted_movies = sorted(list(all_movie_links))
    sorted_movies.reverse() 
    print(f"\n🎯 [BOT {bot_id}] Extraction Complete! Found {len(sorted_movies)} Unique Movie Links.")
    return sorted_movies

def upload_and_sync(meta, tmdb_id, release_year, ident, res_label, f_path, bot_id):
    ext = os.path.splitext(f_path)[1].lower()
    if ext not in [".mp4", ".mkv"]: ext = ".mp4" 
    
    safe_title = clean_filename(meta['title'])
    cf = f"{safe_title}_{release_year}_{res_label}_{tmdb_id}{ext}"
    tp = os.path.join(os.path.dirname(f_path), cf)
    
    if f_path != tp: shutil.move(f_path, tp)
        
    print(f"🚀 [BOT {bot_id}] Uploading {res_label} to Archive.org...")
    time.sleep(1)
    
    try:
        r = ia.upload(
            ident, files=[tp], 
            metadata={"title": f"{meta['title']} ({release_year})", "mediatype": "movies"}, 
            access_key=IA_ACCESS, secret_key=IA_SECRET
        )
        
        if r and r[0].status_code == 200:
            archive_link = f"https://archive.org/download/{ident}/{cf}"
            meta[f"url_{res_label}"] = archive_link
            meta["stream_url"] = archive_link 
            
            requests.patch(f"{FIREBASE_URL}/movies/{tmdb_id}.json", data=json.dumps({f"url_{res_label}": archive_link, "stream_url": archive_link}), timeout=15)
            requests.patch(f"{FIREBASE_URL}/movies/{tmdb_id}.json", data=json.dumps(meta), timeout=15)
            
            print(f"\n🎉 ==================================================")
            print(f"✅ [BOT {bot_id}] SUCCESS: {res_label} UPLOADED & SYNCED!")
            print(f"🎬 Movie: {meta['title']} [{res_label}]")
            print(f"==================================================\n")
            
            try: 
                os.remove(tp)
                print(f"🗑️ [BOT {bot_id}] DISK CLEARED: File deleted locally!\n")
            except Exception: pass
            return True
        else:
            print(f"❌ [BOT {bot_id}] Upload Failed!")
            try: os.remove(tp)
            except: pass
            return False
    except Exception as e:
        print(f"❌ [BOT {bot_id}] Upload Error: {e}")
        try: os.remove(tp)
        except: pass
        return False

def download_with_aria2(url, work_dir, referer_url, bot_id, res_label):
    print(f"📥 [BOT {bot_id}] Downloading {res_label} Directly (8 Connections) -> {url}")
    cmd = [
        "aria2c", "--dir=" + work_dir, "--seed-time=0", 
        "-x", "8", "-s", "8", "-j", "8",
        "-c", "--max-tries=10", "--retry-wait=2", 
        "--min-split-size=5M",
        "--content-disposition-default-utf8=true", f"--referer={referer_url}",
        "--header=User-Agent: Mozilla/5.0",
        url
    ]
    try: subprocess.run(cmd, check=True, timeout=7200)
    except: return None
            
    for root, dirs, files in os.walk(work_dir):
        for file in files:
            if file.lower().endswith((".mp4", ".mkv")) and not file.endswith(".aria2"):
                return os.path.join(root, file)
    return None

def run_bot():
    print(f"🔥 Starting DEEP-CRAWLER Bot ID: {BOT_ID} (Account #{actual_bot_account_id})")
        
    if BOT_ID == 8:
        print(f"🤖 [BOT 8] Live Worker is on Standby for App Users...")
        time.sleep(10)
        return

    completed = 0
    start_time = time.time()
    
    my_movies_links = crawl_filmyzilla_deep_categories(BOT_ID)

    if not my_movies_links:
        print(f"⚠️ [BOT {BOT_ID}] No movies found in assigned categories. Exiting gracefully.")
        return

    for m_url in my_movies_links:
        if completed >= MAX_MOVIES_PER_RUN or (time.time() - start_time) > 20000: break 

        print(f"\n--------------------------------------------------")
        print(f"🛠️ [BOT {BOT_ID}] Step 1: Processing Link -> {m_url}")
        
        try:
            session.headers.update({"Referer": BASE_DOMAIN})
            m_resp = session.get(m_url, timeout=25)
        except: continue
        
        title_match = re.search(r'<title>(.*?)</title>', m_resp.text, re.IGNORECASE)
        raw_title = title_match.group(1) if title_match else ""
        clean_title = clean_title_for_tmdb(raw_title)
        
        if not clean_title: continue
        print(f"🔎 [BOT {BOT_ID}] Step 2: Querying TMDB for exact match: '{clean_title}'")

        url_tmdb = f"https://api.themoviedb.org/3/search/multi?api_key={TMDB_API_KEY}&query={urllib.parse.quote(clean_title)}&language=hi"
        try:
            t_res = requests.get(url_tmdb, timeout=10).json().get("results", [])
            valid = [r for r in t_res if r.get("media_type") in ["movie", "tv"]]
            if not valid: continue
            tmdb_data = valid[0]
        except: continue
            
        tmdb_id = str(tmdb_data["id"])
        
        existing_db_movie = get_firebase_movie_data(tmdb_id)
        if existing_db_movie:
            if existing_db_movie.get("url_480p") and existing_db_movie.get("url_720p") and existing_db_movie.get("url_1080p"):
                print(f"⏩ [BOT {BOT_ID}] All resolutions exist in Firebase! Skipping...")
                continue

        print(f"✅ [BOT {BOT_ID}] Step 3: Extracting Direct Download Links...")
        res_links = {}
        m_hrefs = re.findall(r'<a\s+[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', m_resp.text, re.IGNORECASE | re.DOTALL)
        
        for href, text in m_hrefs:
            t_low = text.lower()
            if "720p" in t_low: res_links["720p"] = urllib.parse.urljoin(BASE_DOMAIN, href)
            elif "1080p" in t_low: res_links["1080p"] = urllib.parse.urljoin(BASE_DOMAIN, href)
            elif "480p" in t_low: res_links["480p"] = urllib.parse.urljoin(BASE_DOMAIN, href)

        if not res_links: continue

        wd = f"/tmp/filmy_{BOT_ID}_{tmdb_id}"
        os.makedirs(wd, exist_ok=True)
        
        t_name = tmdb_data.get('title') or tmdb_data.get('name', 'Untitled')
        release_year = str(tmdb_data.get('release_date') or tmdb_data.get('first_air_date', '2026'))[:4]
        ident = f"sijjhub-media-{tmdb_id}-{int(time.time())}"
        
        meta = {
            "tmdb_id": tmdb_id, "id": tmdb_id, "title": t_name, 
            "overview": tmdb_data.get("overview", ""), "release_date": release_year, 
            "poster": f"https://image.tmdb.org/t/p/w500{tmdb_data.get('poster_path')}" if tmdb_data.get('poster_path') else "", 
            "hindi_dubbed": True, "category": "Trending Movies"
        }

        # 💡 NAYA STEP 4: Seedha Download! (Koi server find nahi karna ab)
        for res_label, direct_download_url in res_links.items():
            
            if existing_db_movie and existing_db_movie.get(f"url_{res_label}"):
                print(f"⏩ [BOT {BOT_ID}] SKIPPING {res_label}: Already in Firebase!")
                continue
                
            print(f"\n⚙️ [BOT {BOT_ID}] Step 4: Initiating Direct Download for {res_label}...")
            try:
                # Direct aria2c ko link pakra diya hai
                f_path = download_with_aria2(direct_download_url, wd, m_url, BOT_ID, res_label)
                
                if f_path: 
                    upload_and_sync(meta, tmdb_id, release_year, ident, res_label, f_path, BOT_ID)
                
                time.sleep(1) 
            except Exception as e:
                print(f"❌ [BOT {BOT_ID}] Error in {res_label}: {e}")

        completed += 1
        shutil.rmtree(wd, ignore_errors=True)
        print(f"✅ [BOT {BOT_ID}] Movie Done! Moving to next...\n")

if __name__ == "__main__":
    run_bot()
