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

MAX_MOVIES_PER_RUN = 30
MAX_CONCURRENT_TASKS = 3

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Referer": BASE_DOMAIN
})

# 💡 EXACT URLs - NO /category/ MISTAKE
BOT_TARGETS = {
    1: "imdb-top-movies",
    2: "bollywood-hindi-movies",
    3: "hollywood-hindi-movies",
    4: "punjabi-movies",
    5: "south-hindi-dubbed-movie",
    6: "web-series",
    7: "front-page-scout",
    8: "animation-movies"
}

def clean_filename(name):
    cleaned = re.sub(r'[^a-zA-Z0-9_-]', '_', name)
    return re.sub(r'_+', '_', cleaned).strip('_')

def clean_title_for_tmdb(raw_title):
    clean = re.sub(r'(?i)\bDownload\b', '', raw_title)
    clean = re.sub(r'(?i)in HD Filmyzilla.*', '', clean)
    clean = re.sub(r'(?i)Filmyzilla', '', clean)
    clean = re.sub(r'(?i)Hindi Dubbed.*', '', clean)
    clean = re.sub(r'(?i)(full movie|hdrip|bluray|web-dl|1080p|720p|480p|hevc|esub|dual audio|web series).*', '', clean)
    clean = re.sub(r'\(\d{4}\)|\[\d{4}\]', '', clean)
    clean = re.sub(r'\(.*?\)|\[.*?\]', '', clean)
    clean = re.sub(r'(?i)part-\d+', '', clean)
    clean = re.sub(r'(?i)s\d{2}', '', clean) 
    return clean.replace('-', ' ').replace('_', ' ').strip()

def get_bot_state():
    try:
        res = requests.get(f"{FIREBASE_URL}/bot_state/bot_{BOT_ID}.json", timeout=5)
        if res.status_code == 200 and res.json():
            return res.json().get("last_visited_pages", [])
    except: pass
    return []

def save_bot_state(visited_pages):
    try:
        requests.put(f"{FIREBASE_URL}/bot_state/bot_{BOT_ID}.json", json={"last_visited_pages": list(visited_pages)[-200:]}) 
    except: pass

def get_strict_movies_for_bot():
    movie_links = set()
    visited_pages = set(get_bot_state())
    
    if BOT_ID == 7: 
        print(f"📡 [BOT 7] SCOUT: Scanning Front Page for latest releases...", flush=True)
        pages_to_scan = [BASE_DOMAIN, f"{BASE_DOMAIN}/page/2/", f"{BASE_DOMAIN}/page/3/", f"{BASE_DOMAIN}/page/4/"]
        for p_url in pages_to_scan:
            try:
                resp = session.get(p_url, timeout=15)
                for match in re.finditer(r'<a\s+[^>]*href=["\']([^"\']+\.html)["\'][^>]*>', resp.text, re.IGNORECASE):
                    movie_links.add(urllib.parse.urljoin(BASE_DOMAIN, match.group(1)))
            except: pass
        return list(movie_links)

    category_slug = BOT_TARGETS.get(BOT_ID)
    base_cat_url = f"{BASE_DOMAIN}/{category_slug}/"
    
    print(f"🔥 [BOT {BOT_ID}] STRICT SWEEP: {category_slug}", flush=True)
    
    for p_num in range(1, 10): 
        p_url = base_cat_url if p_num == 1 else f"{base_cat_url}page/{p_num}/"
        if p_url not in visited_pages:
            try:
                resp = session.get(p_url, timeout=15)
                if resp.status_code == 404: break 
                found_any = False
                for match in re.finditer(r'<a\s+[^>]*href=["\']([^"\']+\.html)["\'][^>]*>', resp.text, re.IGNORECASE):
                    movie_links.add(urllib.parse.urljoin(BASE_DOMAIN, match.group(1)))
                    found_any = True
                
                visited_pages.add(p_url)
                if not found_any: break
            except: pass

    alphabets = [chr(i) for i in range(65, 91)] 
    for letter in alphabets:
        az_url = f"{base_cat_url}?sort={letter}"
        for page_num in range(1, 21):
            target_url = az_url if page_num == 1 else f"{az_url}&page={page_num}"
            if target_url in visited_pages: continue 
            try:
                resp = session.get(target_url, timeout=15)
                if resp.status_code == 404 or "No movies found" in resp.text: break
                
                found_any = False
                for match in re.finditer(r'<a\s+[^>]*href=["\']([^"\']+\.html)["\'][^>]*>', resp.text, re.IGNORECASE):
                    movie_links.add(urllib.parse.urljoin(BASE_DOMAIN, match.group(1)))
                    found_any = True
                
                visited_pages.add(target_url)
                if not found_any: break 
            except: pass

    save_bot_state(visited_pages)
    return list(movie_links)

def upload_and_sync(meta, tmdb_id, ident, res_label, f_path, bot_id, part_suffix=""):
    try:
        file_size_mb = os.path.getsize(f_path) / (1024 * 1024)
        if file_size_mb < 50: 
            print(f"⚠️ [BOT {bot_id}] FAKE FILE DETECTED! '{meta['title']}' is only {file_size_mb:.2f}MB. Deleting!", flush=True)
            os.remove(f_path)
            return False
    except:
        return False

    ext = os.path.splitext(f_path)[1].lower()
    if ext not in [".mp4", ".mkv"]: ext = ".mp4" 
    
    release_year = meta.get("release_date", "2026")
    safe_title = clean_filename(meta['title'])
    file_name = f"{safe_title}_{release_year}{part_suffix}_{res_label}_{tmdb_id}{ext}"
    tp = os.path.join(os.path.dirname(f_path), file_name)
    
    if f_path != tp: shutil.move(f_path, tp)
    
    max_retries = 5
    for attempt in range(max_retries):
        print(f"🚀 [BOT {bot_id}] UPLOADING: {meta['title']} {part_suffix} [{res_label}] (Size: {file_size_mb:.2f} MB)...", flush=True)
        try:
            r = ia.upload(
                ident, files=[tp], 
                metadata={"title": f"{meta['title']} {part_suffix} ({release_year})", "mediatype": "movies"}, 
                access_key=IA_ACCESS, secret_key=IA_SECRET
            )
            
            if r and r[0].status_code == 200:
                print(f"✅ [BOT {bot_id}] {res_label} UPLOAD SUCCESS! Syncing to DB...", flush=True)
                archive_link = f"https://archive.org/download/{ident}/{file_name}"
                db_key = f"url_{res_label}{part_suffix.replace('-', '_')}"
                
                meta[db_key] = archive_link
                meta["stream_url"] = archive_link 
                
                requests.patch(f"{FIREBASE_URL}/movies/{tmdb_id}.json", data=json.dumps({db_key: archive_link, "stream_url": archive_link}), timeout=15)
                requests.patch(f"{FIREBASE_URL}/movies/{tmdb_id}.json", data=json.dumps(meta), timeout=15)
                
                os.remove(tp)
                return True
        except Exception as e:
            print(f"❌ [BOT {bot_id}] Archive Error: {e}", flush=True)
            if attempt < max_retries - 1:
                time.sleep(60)
            else:
                try: os.remove(tp)
                except: pass
                return False
    return False

def download_with_aria2(url, work_dir, referer_url, bot_id, res_label, movie_title):
    print(f"📥 [BOT {bot_id}] DOWNLOADING: {movie_title} [{res_label}]...", flush=True)
    cmd = [
        "aria2c", "--dir=" + work_dir, "--seed-time=0", 
        "-x", "4", "-s", "4", 
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

def process_single_content(m_url):
    try:
        session.headers.update({"Referer": BASE_DOMAIN})
        m_resp = session.get(m_url, timeout=25)
    except: return
    
    title_match = re.search(r'<title>(.*?)</title>', m_resp.text, re.IGNORECASE)
    raw_title = title_match.group(1) if title_match else ""
    clean_name = clean_title_for_tmdb(raw_title)
    if not clean_name: return

    is_series = BOT_ID == 6 or "series" in raw_title.lower() or "season" in raw_title.lower()
    search_type = "tv" if is_series else "multi"

    url_tmdb = f"https://api.themoviedb.org/3/search/{search_type}?api_key={TMDB_API_KEY}&query={urllib.parse.quote(clean_name)}&language=en-US"
    try:
        t_res = requests.get(url_tmdb, timeout=10).json().get("results", [])
        if not t_res: 
            print(f"❌ [BOT {BOT_ID}] SKIPPED: '{clean_name}' (TMDB par nahi mili)", flush=True)
            return
        tmdb_data = t_res[0]
    except: return
        
    tmdb_id = str(tmdb_data["id"])
    
    try:
        res_check = requests.get(f"{FIREBASE_URL}/movies/{tmdb_id}.json", timeout=5)
        if res_check.status_code == 200 and res_check.json():
            data = res_check.json()
            if data.get("url_480p") and data.get("url_720p"): 
                print(f"⏭️ [BOT {BOT_ID}] SKIPPED: '{clean_name}' (Pehle se Database mein maujood hai)", flush=True)
                return 
    except: pass

    # 💡 EPISODES FIX (Ab har episode alag number ke sath save hogi)
    download_queue = [] 
    for href, link_text in re.findall(r'<a\s+[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', m_resp.text, re.IGNORECASE | re.DOTALL):
        t_low = link_text.lower()
        if "download" in t_low:
            res = "720p" if "720p" in t_low else ("1080p" if "1080p" in t_low else ("480p" if "480p" in t_low else None))
            if res: download_queue.append((res, urllib.parse.urljoin(BASE_DOMAIN, href)))

    # Remove identical duplicate URLs but KEEP episodes
    unique_urls = []
    seen = set()
    for res, link in download_queue:
        if link not in seen:
            unique_urls.append((res, link))
            seen.add(link)
            
    final_download_queue = []
    res_counters = {"480p": 1, "720p": 1, "1080p": 1}
    
    for res, link in unique_urls:
        suffix = f"_Ep{res_counters[res]}" if is_series else (f"_Pt{res_counters[res]}" if res_counters[res] > 1 else "")
        final_download_queue.append((res, link, suffix))
        res_counters[res] += 1
    
    if not final_download_queue: 
        print(f"⚠️ [BOT {BOT_ID}] SKIPPED: '{clean_name}' (Page par Download link nahi mila)", flush=True)
        return

    wd = f"/tmp/sijj_{BOT_ID}_{tmdb_id}"
    os.makedirs(wd, exist_ok=True)
    
    t_name = tmdb_data.get('title') or tmdb_data.get('name', 'Untitled')
    release_year = str(tmdb_data.get('release_date') or tmdb_data.get('first_air_date', '2026'))[:4]
    ident = f"sijjhub-media-{tmdb_id}-{int(time.time())}"
    
    meta = {
        "tmdb_id": tmdb_id, "id": tmdb_id, "title": t_name, 
        "overview": tmdb_data.get("overview", ""), "release_date": release_year, 
        "poster": f"https://image.tmdb.org/t/p/w500{tmdb_data.get('poster_path')}" if tmdb_data.get('poster_path') else "", 
        "hindi_dubbed": True, "category": BOT_TARGETS.get(BOT_ID, "Trending").replace('-', ' ').title(),
        "is_series": is_series
    }

    for res_label, direct_url, part_suffix in final_download_queue:
        f_path = download_with_aria2(direct_url, wd, m_url, BOT_ID, res_label, meta['title'])
        if f_path: 
            upload_and_sync(meta, tmdb_id, ident, res_label, f_path, BOT_ID, part_suffix)

    shutil.rmtree(wd, ignore_errors=True)

def run_bot():
    print(f"🔥 Starting Bot ID: {BOT_ID} (Duty: {BOT_TARGETS.get(BOT_ID)}) - Account #{actual_bot_account_id}", flush=True)

    if BOT_ID == 8:
        try:
            req_res = requests.get(f"{FIREBASE_URL}/requests.json", timeout=10)
            if req_res.status_code == 200 and req_res.json():
                requests_dict = req_res.json()
                for req_id, req_data in requests_dict.items():
                    if req_data.get("status") == "pending":
                        requests.patch(f"{FIREBASE_URL}/requests/{req_id}.json", json={"status": "processing"})
        except: pass

    movie_links = get_strict_movies_for_bot()
    print(f"🎯 [BOT {BOT_ID}] Found {len(movie_links)} targets. Initiating Downloads...", flush=True)

    start_time = time.time()
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_CONCURRENT_TASKS) as executor:
        futures = []
        for m_url in movie_links[:MAX_MOVIES_PER_RUN]:
            if (time.time() - start_time) > 20000: break 
            futures.append(executor.submit(process_single_content, m_url))
        
        concurrent.futures.wait(futures)
        
    print(f"🏁 [BOT {BOT_ID}] FACTORY RUN COMPLETE!", flush=True)

if __name__ == "__main__":
    run_bot()
