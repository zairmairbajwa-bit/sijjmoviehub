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
import concurrent.futures

# === SECURE CREDENTIALS ===
TMDB_API_KEY = os.getenv("TMDB_API_KEY", "").strip() or "7b6a89d3dc55b3a81aa892a88c0da6b9"
FIREBASE_URL = os.getenv("FIREBASE_URL", "").strip() or "https://sijjmoviehub-default-rtdb.firebaseio.com"
BASE_DOMAIN = "https://filmicity.in"

BOT_ID = int(os.getenv("BOT_ID", "1") or "1")
TOTAL_BOTS = 8

actual_bot_account_id = ((BOT_ID - 1) % 4) + 1
IA_ACCESS = os.getenv(f"IA_ACCESS_{actual_bot_account_id}", "").strip()
IA_SECRET = os.getenv(f"IA_SECRET_{actual_bot_account_id}", "").strip()

MAX_MOVIES_PER_RUN = 30 # Parallel processing ki wajah se limit badha di
MAX_CONCURRENT_TASKS = 3 # Ek waqt mein 3 movies process hongi

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
    clean = re.sub(r'(?i)(full movie|hdrip|bluray|web-dl|1080p|720p|480p|hevc|esub|dual audio).*', '', clean)
    clean = re.sub(r'\(\d{4}\)|\[\d{4}\]', '', clean)
    clean = re.sub(r'\(.*?\)|\[.*?\]', '', clean)
    return clean.replace('-', ' ').replace('_', ' ').strip()

# 💡 SMART MEMORY: Firebase se check karega aakhri dafa kahan tha
def get_bot_state():
    try:
        res = requests.get(f"{FIREBASE_URL}/bot_state/bot_{BOT_ID}.json", timeout=5)
        if res.status_code == 200 and res.json():
            return res.json().get("last_visited_pages", [])
    except: pass
    return []

def save_bot_state(visited_pages):
    try:
        requests.put(f"{FIREBASE_URL}/bot_state/bot_{BOT_ID}.json", json={"last_visited_pages": list(visited_pages)[-50:]})
    except: pass

# 💡 BOTS DEEP CRAWLER
def get_movies_for_bot():
    movie_links = set()
    visited_pages = set(get_bot_state()) # Purani memory load ki
    
    print(f"🔥 [BOT {BOT_ID}] Scanning for New Movies & Resuming Previous State...", flush=True)
    
    # Hamesha front page / recent pages scan karega naye content ke liye
    for page in range(1, 5):
        url = BASE_DOMAIN if page == 1 else f"{BASE_DOMAIN}/page/{page}/"
        try:
            resp = session.get(url, timeout=15)
            matches = re.finditer(r'<a\s+[^>]*href=["\']([^"\']+\.html)["\'][^>]*>', resp.text, re.IGNORECASE)
            for match in matches:
                full_url = urllib.parse.urljoin(BASE_DOMAIN, match.group(1))
                if "/movie/" in full_url.lower() and full_url not in visited_pages:
                    movie_links.add(full_url)
        except: pass

    # Phir apni specific categories/years deep scan karega
    if BOT_ID > 1:
        try:
            r = session.get(BASE_DOMAIN, timeout=15)
            cat_urls = [urllib.parse.urljoin(BASE_DOMAIN, m.group(1)) for m in re.finditer(r'<a\s+[^>]*href=["\']([^"\']+)["\'][^>]*>', r.text, re.IGNORECASE) if "/category/" in m.group(1).lower()]
            my_categories = cat_urls[(BOT_ID - 2) :: 6] if len(cat_urls) >= 6 else cat_urls
            
            for cat_url in my_categories:
                # Go deep into pages of category (page 1 to 20)
                for cat_page in range(1, 20):
                    p_url = cat_url if cat_page == 1 else f"{cat_url}page/{cat_page}/"
                    if p_url in visited_pages: continue # Skip if already fully processed in previous run
                    
                    try:
                        c_resp = session.get(p_url, timeout=15)
                        if c_resp.status_code == 404: break # Category pages khatam
                        sub_matches = re.finditer(r'<a\s+[^>]*href=["\']([^"\']+\.html)["\'][^>]*>', c_resp.text, re.IGNORECASE)
                        for match in sub_matches:
                            movie_links.add(urllib.parse.urljoin(BASE_DOMAIN, match.group(1)))
                        visited_pages.add(p_url)
                    except: pass
        except: pass
        
    save_bot_state(visited_pages) # Memory save kar li
    return list(movie_links)

# 💡 ZIDDI UPLOAD LOGIC (RETRY SYSTEM)
def upload_and_sync(meta, tmdb_id, release_year, ident, res_label, f_path, bot_id):
    ext = os.path.splitext(f_path)[1].lower()
    if ext not in [".mp4", ".mkv"]: ext = ".mp4" 
    
    safe_title = clean_filename(meta['title'])
    cf = f"{safe_title}_{release_year}_{res_label}_{tmdb_id}{ext}"
    tp = os.path.join(os.path.dirname(f_path), cf)
    
    if f_path != tp: shutil.move(f_path, tp)
    
    max_retries = 5
    for attempt in range(max_retries):
        print(f"🚀 [BOT {bot_id}] ARCHIVE UPLOAD ATTEMPT {attempt+1}/{max_retries} FOR {res_label}...", flush=True)
        try:
            r = ia.upload(
                ident, files=[tp], 
                metadata={"title": f"{meta['title']} ({release_year})", "mediatype": "movies"}, 
                access_key=IA_ACCESS, secret_key=IA_SECRET
            )
            
            if r and r[0].status_code == 200:
                print(f"✅ [BOT {bot_id}] {res_label} UPLOAD SUCCESS! Syncing Database...", flush=True)
                archive_link = f"https://archive.org/download/{ident}/{cf}"
                meta[f"url_{res_label}"] = archive_link
                meta["stream_url"] = archive_link 
                
                requests.patch(f"{FIREBASE_URL}/movies/{tmdb_id}.json", data=json.dumps({f"url_{res_label}": archive_link, "stream_url": archive_link}), timeout=15)
                requests.patch(f"{FIREBASE_URL}/movies/{tmdb_id}.json", data=json.dumps(meta), timeout=15)
                
                os.remove(tp)
                print(f"🗑️ [BOT {bot_id}] LOCAL FILE DELETED SUCCESSFULLY! ({res_label})\n", flush=True)
                return True
        except Exception as e:
            print(f"❌ [BOT {bot_id}] Archive Error on {res_label}: {e}", flush=True)
            if attempt < max_retries - 1:
                print(f"⏳ Waiting 2 minutes before retrying {res_label}...", flush=True)
                time.sleep(120)
            else:
                print(f"🚨 5 ATTEMPTS FAILED. Deleting local file to free space.")
                try: os.remove(tp)
                except: pass
                return False
    return False

def download_with_aria2(url, work_dir, referer_url, bot_id, res_label):
    print(f"📥 [BOT {bot_id}] DOWNLOADING {res_label}...", flush=True)
    cmd = [
        "aria2c", "--dir=" + work_dir, "--seed-time=0", 
        "-x", "4", "-s", "4", # Speed badhane ke liye 4 connections open kiye
        "-c", "--max-tries=10", "--retry-wait=2", 
        "--content-disposition-default-utf8=true", f"--referer={referer_url}",
        "--header=User-Agent: Mozilla/5.0", url
    ]
    try: subprocess.run(cmd, check=True, timeout=7200, stdout=subprocess.DEVNULL)
    except: return None
            
    for root, dirs, files in os.walk(work_dir):
        for file in files:
            if file.lower().endswith((".mp4", ".mkv")) and not file.endswith(".aria2"):
                return os.path.join(root, file)
    return None

# 💡 WORKER THREAD: Ek movie ko handle karega
def process_single_movie(m_url):
    try:
        session.headers.update({"Referer": BASE_DOMAIN})
        m_resp = session.get(m_url, timeout=25)
    except: return
    
    title_match = re.search(r'<title>(.*?)</title>', m_resp.text, re.IGNORECASE)
    clean_name = clean_title_for_tmdb(title_match.group(1) if title_match else "")
    if not clean_name: return

    url_tmdb = f"https://api.themoviedb.org/3/search/multi?api_key={TMDB_API_KEY}&query={urllib.parse.quote(clean_name)}&language=en-US"
    try:
        t_res = requests.get(url_tmdb, timeout=10).json().get("results", [])
        valid = [r for r in t_res if r.get("media_type") in ["movie", "tv"]]
        if not valid: return
        tmdb_data = valid[0]
    except: return
        
    tmdb_id = str(tmdb_data["id"])
    
    # 💡 Smart Check
    try:
        res_check = requests.get(f"{FIREBASE_URL}/movies/{tmdb_id}.json", timeout=5)
        if res_check.status_code == 200 and res_check.json():
            data = res_check.json()
            if data.get("url_480p") and data.get("url_720p"): return # Already fully exists
    except: pass

    res_links = {}
    for href, text in re.findall(r'<a\s+[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', m_resp.text, re.IGNORECASE | re.DOTALL):
        t_low = text.lower()
        if "download" in t_low:
            if "720p" in t_low: res_links["720p"] = urllib.parse.urljoin(BASE_DOMAIN, href)
            elif "480p" in t_low: res_links["480p"] = urllib.parse.urljoin(BASE_DOMAIN, href)

    if not res_links: return

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

    for res_label, url in res_links.items():
        f_path = download_with_aria2(url, wd, m_url, BOT_ID, res_label)
        if f_path: 
            upload_and_sync(meta, tmdb_id, release_year, ident, res_label, f_path, BOT_ID)

    shutil.rmtree(wd, ignore_errors=True)

def run_bot():
    print(f"🔥 Starting Bot ID: {BOT_ID} (Account #{actual_bot_account_id})", flush=True)
    if BOT_ID == 8:
        print(f"🤖 [BOT 8] Live Worker is on Standby...", flush=True)
        time.sleep(10)
        return

    movie_links = get_movies_for_bot()
    random.shuffle(movie_links)
    print(f"🎯 [BOT {BOT_ID}] Found {len(movie_links)} targets. Initiating Multi-Threading...", flush=True)

    # 💡 MULTI-THREADING (Tez Raftar)
    start_time = time.time()
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_CONCURRENT_TASKS) as executor:
        futures = []
        for m_url in movie_links[:MAX_MOVIES_PER_RUN]:
            if (time.time() - start_time) > 20000: break 
            futures.append(executor.submit(process_single_movie, m_url))
        
        concurrent.futures.wait(futures)
        
    print(f"🏁 [BOT {BOT_ID}] RUN COMPLETE!", flush=True)

if __name__ == "__main__":
    run_bot()
