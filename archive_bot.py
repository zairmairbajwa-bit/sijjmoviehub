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
BASE_DOMAIN = "https://filmicity.in"

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

def clean_title_for_tmdb(raw_title):
    clean = re.sub(r'(?i)\bDownload\b', '', raw_title)
    clean = re.sub(r'(?i)in HD Filmyzilla.*', '', clean)
    clean = re.sub(r'(?i)Filmyzilla', '', clean)
    clean = re.sub(r'(?i)Hindi Dubbed.*', '', clean)
    clean = re.sub(r'(?i)(full movie|hdrip|bluray|web-dl|1080p|720p|480p|hevc|esub).*', '', clean)
    clean = re.sub(r'\(\d{4}\)|\[\d{4}\]', '', clean)
    clean = re.sub(r'\(.*?\)|\[.*?\]', '', clean)
    return clean.replace('-', ' ').replace('_', ' ').strip()

# 💡 BOT 1: Front Page (Latest Updates / Trending)
def get_front_page_movies():
    movie_links = set()
    print(f"🔥 [BOT 1] Scraping FRONT PAGE (Trending / Latest Updates)...")
    
    # Homepage aur aglay pages se movies uthana
    for page in range(1, 4):
        url = BASE_DOMAIN if page == 1 else f"{BASE_DOMAIN}/page/{page}/"
        try:
            resp = session.get(url, timeout=15)
            if resp.status_code == 200:
                # Website ke saare .html links jo movie pages ho sakte hain
                matches = re.finditer(r'<a\s+[^>]*href=["\']([^"\']+\.html)["\'][^>]*>(.*?)</a>', resp.text, re.IGNORECASE | re.DOTALL)
                for match in matches:
                    href = match.group(1)
                    full_url = urllib.parse.urljoin(BASE_DOMAIN, href)
                    if "/movie/" in full_url.lower() or ("-" in full_url and "page" not in full_url and "category" not in full_url and "index" not in full_url):
                        movie_links.add(full_url)
        except Exception as e:
            print(f"⚠️ Front page error: {e}")
            
    links = list(movie_links)
    print(f"🎯 [BOT 1] Found {len(links)} movies from Front Page.")
    return links

# 💡 BOTS 2-7: Categories & Year Folders Crawler
def get_category_year_movies(bot_id):
    print(f"📁 [BOT {bot_id}] Crawling Category & Year Folders...")
    try:
        r = session.get(BASE_DOMAIN, timeout=15)
    except: return []
    
    category_urls = []
    matches = re.finditer(r'<a\s+[^>]*href=["\']([^"\']+)["\'][^>]*>', r.text, re.IGNORECASE)
    for match in matches:
        href = match.group(1)
        full_url = urllib.parse.urljoin(BASE_DOMAIN, href)
        if full_url.startswith(BASE_DOMAIN) and ("/category/" in full_url.lower() or "movies" in full_url.lower() or "series" in full_url.lower()):
            if full_url not in category_urls and full_url != BASE_DOMAIN:
                category_urls.append(full_url)
                
    category_urls = sorted(list(set(category_urls)))
    my_categories = category_urls[(bot_id - 2) :: 6] if len(category_urls) >= 6 else category_urls
    
    all_movie_links = set()
    visited_pages = set()
    
    for cat_url in my_categories:
        print(f"🕷️ [BOT {bot_id}] Entering Category: {cat_url}")
        to_visit = [cat_url]
        pages_crawled = 0
        
        while to_visit and pages_crawled < 20:
            current_url = to_visit.pop(0)
            if current_url in visited_pages: continue
            visited_pages.add(current_url)
            pages_crawled += 1
            
            try:
                resp = session.get(current_url, timeout=15)
                sub_matches = re.finditer(r'<a\s+[^>]*href=["\']([^"\']+)["\'][^>]*>', resp.text, re.IGNORECASE)
                
                for match in sub_matches:
                    shref = match.group(1)
                    sfull = urllib.parse.urljoin(BASE_DOMAIN, shref)
                    if not sfull.startswith(BASE_DOMAIN): continue
                    
                    if "/movie/" in sfull.lower() or (sfull.endswith(".html") and "category" not in sfull.lower() and "index" not in sfull.lower()):
                        all_movie_links.add(sfull)
                    elif "category" in sfull.lower() or "default" in sfull.lower() or re.search(r'\b(20\d\d|19\d\d)\b', sfull):
                        if sfull not in visited_pages and sfull not in to_visit:
                            to_visit.append(sfull)
            except: pass
            
    return list(all_movie_links)

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
    print(f"🔥 Starting Dedicated-Crawler Bot ID: {BOT_ID} (Account #{actual_bot_account_id})")
        
    if BOT_ID == 8:
        print(f"🤖 [BOT 8] Live Worker is on Standby...")
        time.sleep(10)
        return

    completed = 0
    start_time = time.time()
    
    if BOT_ID == 1:
        movie_links = get_front_page_movies()
    else:
        movie_links = get_category_year_movies(BOT_ID)
        
    random.shuffle(movie_links)
    print(f"🎯 [BOT {BOT_ID}] Total targeted movies to process: {len(movie_links)}")

    for m_url in movie_links:
        if completed >= MAX_MOVIES_PER_RUN or (time.time() - start_time) > 20000: break 

        print(f"\n--------------------------------------------------")
        print(f"🛠️ [BOT {BOT_ID}] Step 1: Processing URL -> {m_url}")
        
        try:
            session.headers.update({"Referer": BASE_DOMAIN})
            m_resp = session.get(m_url, timeout=25)
        except: continue
        
        title_match = re.search(r'<title>(.*?)</title>', m_resp.text, re.IGNORECASE)
        raw_title = title_match.group(1) if title_match else ""
        clean_name = clean_title_for_tmdb(raw_title)
        
        if not clean_name: continue
        print(f"🔎 [BOT {BOT_ID}] Step 2: Querying TMDB for metadata: '{clean_name}'")

        url_tmdb = f"https://api.themoviedb.org/3/search/multi?api_key={TMDB_API_KEY}&query={urllib.parse.quote(clean_name)}&language=en-US"
        try:
            t_res = requests.get(url_tmdb, timeout=10).json().get("results", [])
            valid = [r for r in t_res if r.get("media_type") in ["movie", "tv"]]
            if not valid: continue
            tmdb_data = valid[0]
        except: continue
            
        tmdb_id = str(tmdb_data["id"])
        
        try:
            res_check = requests.get(f"{FIREBASE_URL}/movies/{tmdb_id}.json", timeout=5)
            if res_check.status_code == 200 and res_check.json():
                data = res_check.json()
                if data.get("url_480p") and data.get("url_720p"):
                    print(f"⏩ [BOT {BOT_ID}] Already fully processed in Firebase! Skipping...")
                    continue
        except: pass

        print(f"✅ [BOT {BOT_ID}] Step 3: Extracting Direct Download Links...")
        res_links = {}
        m_hrefs = re.findall(r'<a\s+[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', m_resp.text, re.IGNORECASE | re.DOTALL)
        for href, text in m_hrefs:
            t_low = text.lower()
            if "download" in t_low:
                if "720p" in t_low: res_links["720p"] = urllib.parse.urljoin(BASE_DOMAIN, href)
                elif "1080p" in t_low: res_links["1080p"] = urllib.parse.urljoin(BASE_DOMAIN, href)
                elif "480p" in t_low: res_links["480p"] = urllib.parse.urljoin(BASE_DOMAIN, href)

        if not res_links: 
            print(f"⚠️ [BOT {BOT_ID}] No direct download links found.")
            continue

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

        for res_label, direct_download_url in res_links.items():
            print(f"\n⚙️ [BOT {BOT_ID}] Step 4: Direct Downloading {res_label}...")
            try:
                f_path = download_with_aria2(direct_download_url, wd, m_url, BOT_ID, res_label)
                if f_path: 
                    upload_and_sync(meta, tmdb_id, release_year, ident, res_label, f_path, bot_id)
                time.sleep(1) 
            except Exception as e:
                print(f"❌ [BOT {BOT_ID}] Error in {res_label}: {e}")

        completed += 1
        shutil.rmtree(wd, ignore_errors=True)
        print(f"✅ [BOT {BOT_ID}] Movie Done! Moving to next...\n")

if __name__ == "__main__":
    run_bot()
