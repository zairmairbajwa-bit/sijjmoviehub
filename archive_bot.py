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

# === SECURE CREDENTIALS & NEW DOMAIN ===
TMDB_API_KEY = os.getenv("TMDB_API_KEY", "").strip() or "7b6a89d3dc55b3a81aa892a88c0da6b9"
FIREBASE_URL = os.getenv("FIREBASE_URL", "").strip() or "https://sijjmoviehub-default-rtdb.firebaseio.com"
BASE_DOMAIN = "https://www.filmyzilla84.com" # Naya Domain Set Kar Diya Hai

BOT_ID = int(os.getenv("BOT_ID", "1") or "1")
TOTAL_BOTS = 8

actual_bot_account_id = ((BOT_ID - 1) % 4) + 1
IA_ACCESS = os.getenv(f"IA_ACCESS_{actual_bot_account_id}", "").strip()
IA_SECRET = os.getenv(f"IA_SECRET_{actual_bot_account_id}", "").strip()

# 💡 500 MOVIE LIMIT & 1-BY-1 DOWNLOAD (Disk space safe rahegi)
MAX_MOVIES_PER_RUN = 500
MAX_CONCURRENT_TASKS = 1 

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Referer": BASE_DOMAIN
})

# 💡 8 BOTS KI NAYI DUTIES AUR EXACT RASTE LAGA DIYE HAIN
BOT_TARGETS = {
    1: "category/405/2026-latest-bollywood-movies",
    2: "category/398/2025-latest-bollywood-movies",
    3: "category/347/2024-latest-bollywood-movies",
    4: "category/266/New-bollywood-movies-2023",
    5: "category/250/New-bollywood-movies-2022",
    6: "category/251/New-bollywood-movies-2021",
    7: "category/252/Latest-bollywood-movies-2020",
    8: "category/253/Latest-bollywood-movies-2019"
}

def clean_filename(name):
    cleaned = re.sub(r'[^a-zA-Z0-9_-]', '_', name)
    return re.sub(r'_+', '_', cleaned).strip('_')

def clean_title_for_tmdb(raw_title):
    if "Catalog" in raw_title or "Latest Bollywood" in raw_title or "FilmyZilla" in raw_title:
        return None
        
    clean = raw_title
    clean = re.sub(r'(?i)Bollywood Hindi Movie.*', '', clean)
    clean = re.sub(r'(?i)Hollywood Hindi Movie.*', '', clean)
    clean = re.sub(r'(?i)South Hindi Dubbed.*', '', clean)
    clean = re.sub(r'(?i)HQCam Movie.*', '', clean)
    clean = re.sub(r'(?i)in HD Filmyzilla.*', '', clean)
    clean = re.sub(r'(?i)Filmyzilla', '', clean)
    clean = re.sub(r'(?i)Hindi Dubbed.*', '', clean)
    clean = re.sub(r'(?i)\bDownload\b', '', clean)
    clean = re.sub(r'(?i)(full movie|hdrip|bluray|web-dl|webrip|1080p|720p|480p|hevc|esub|dual audio|web series).*', '', clean)
    clean = re.sub(r'\(\d{4}\)|\[\d{4}\]', '', clean)
    clean = re.sub(r'\(.*?\)|\[.*?\]', '', clean)
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

# 💡 SMART URL VALIDATOR (Ab sirf aur sirf asli Movies pakrega!)
def is_valid_movie_url(url):
    low = url.lower()
    # Asli movies ke URL mein hamesha '/movie/' hota hai. Menu links mein nahi hota.
    if "/movie/" in low and low.endswith(".html"):
        return True
    return False

def get_strict_movies_for_bot():
    movie_links = set()
    visited_pages = set(get_bot_state())
    
    category_slug = BOT_TARGETS.get(BOT_ID)
    base_cat_url = f"{BASE_DOMAIN}/{category_slug}/default/"
    
    print(f"🔥 [BOT {BOT_ID}] STRICT SWEEP: {category_slug}", flush=True)
    
    # 💡 NAYA RASTA: 1.html, 2.html, 3.html...
    for p_num in range(1, 51): 
        p_url = f"{base_cat_url}{p_num}.html"
        
        if p_url in visited_pages: continue
        
        try:
            print(f"📄 [BOT {BOT_ID}] Scanning Page {p_num}: {p_url}", flush=True)
            resp = session.get(p_url, timeout=15)
            if resp.status_code == 404 or "Not Found" in resp.text: 
                print(f"🛑 [BOT {BOT_ID}] Reached end of category pages at Page {p_num}.", flush=True)
                break 
                
            found_any = False
            for match in re.finditer(r'<a\s+[^>]*href=["\']([^"\']+)["\'][^>]*>', resp.text, re.IGNORECASE):
                link = urllib.parse.urljoin(BASE_DOMAIN, match.group(1))
                if is_valid_movie_url(link):
                    movie_links.add(link)
                    found_any = True
            
            visited_pages.add(p_url)
            if not found_any: 
                print(f"⚠️ [BOT {BOT_ID}] No movies found on Page {p_num}. End of list.", flush=True)
                break
        except Exception as e:
            print(f"❌ [BOT {BOT_ID}] Error scanning page {p_num}: {e}", flush=True)
            break

    save_bot_state(visited_pages)
    return list(movie_links)

def upload_and_sync(meta, tmdb_id, ident, res_label, f_path, bot_id, part_suffix=""):
    try:
        ext = os.path.splitext(f_path)[1].lower()
        if ext not in [".mp4", ".mkv"]: ext = ".mp4" 
        
        release_year = meta.get("release_date", "2026")
        safe_title = clean_filename(meta['title'])
        file_name = f"{safe_title}_{release_year}{part_suffix}_{res_label}_{tmdb_id}{ext}"
        tp = os.path.join(os.path.dirname(f_path), file_name)
        
        if f_path != tp: shutil.move(f_path, tp)
        
        max_retries = 3
        for attempt in range(max_retries):
            print(f"🚀 [BOT {bot_id}] UPLOADING: {meta['title']} [{res_label}] (Attempt {attempt+1}/{max_retries})...", flush=True)
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
                time.sleep(10)
                
        # Agar upload poori tarah fail ho jaye toh file delete kar do taake space na ruke
        try: os.remove(tp)
        except: pass
        return False
    except:
        return False

# 💡 SMART SERVER HUNTER: Resolution page se Servers dhundega (Priority: Server 3, Server 4)
def get_server_links(res_page_url):
    try:
        resp = session.get(res_page_url, timeout=15)
        servers = []
        for match in re.finditer(r'<a\s+[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', resp.text, re.IGNORECASE):
            link = urllib.parse.urljoin(BASE_DOMAIN, match.group(1))
            text = match.group(2).lower()
            if "server" in text or "download" in text:
                servers.append((text, link))
        
        priority_servers = []
        other_servers = []
        for text, link in servers:
            if "server 3" in text or "server 4" in text:
                priority_servers.append(link)
            else:
                other_servers.append(link)
        
        # Pehle Server 3/4 try karega, uske baad baqi
        return priority_servers + other_servers
    except:
        return []

def download_with_aria2(url, work_dir, referer_url):
    cmd = [
        "aria2c", "--dir=" + work_dir, "--seed-time=0", 
        "-x", "4", "-s", "4", 
        "-c", "--max-tries=3", "--retry-wait=2", "--connect-timeout=15",
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

# 💡 HIT AND TRIAL SYSTEM: Servers ko bari bari check karega, jo pehla chal gaya uspe rukk jayega
def hit_and_trial_download(server_links, work_dir, referer, bot_id, res_label, title):
    for s_link in server_links:
        print(f"🔄 [BOT {bot_id}] Trying Server: {s_link.split('/')[-1][:20]}...", flush=True)
        f_path = download_with_aria2(s_link, work_dir, referer)
        if f_path:
            file_size_mb = os.path.getsize(f_path) / (1024 * 1024)
            if file_size_mb > 50: # File 50MB se bari hai toh matlab real movie hai
                print(f"🟢 [BOT {bot_id}] SUCCESS! Downloading from this server.", flush=True)
                return f_path
            else:
                print(f"⚠️ [BOT {bot_id}] FAKE FILE ({file_size_mb:.2f}MB). Trying next server...", flush=True)
                os.remove(f_path)
    return None

def process_single_content(m_url):
    try:
        session.headers.update({"Referer": BASE_DOMAIN})
        m_resp = session.get(m_url, timeout=25)
    except: return
    
    title_match = re.search(r'<title>(.*?)</title>', m_resp.text, re.IGNORECASE)
    raw_title = title_match.group(1) if title_match else ""
    
    clean_name = clean_title_for_tmdb(raw_title)
    if not clean_name: 
        return

    # TMDB Par Check
    url_tmdb = f"https://api.themoviedb.org/3/search/multi?api_key={TMDB_API_KEY}&query={urllib.parse.quote(clean_name)}&language=en-US"
    try:
        t_res = requests.get(url_tmdb, timeout=10).json().get("results", [])
        if not t_res: 
            print(f"❌ [BOT {BOT_ID}] TMDB NOT FOUND SKIPPED: '{clean_name}'", flush=True)
            return
        tmdb_data = t_res[0]
    except: return
        
    tmdb_id = str(tmdb_data["id"])
    
    # 💡 FIREBASE DB CHECK (Duplicate rokne ke liye)
    try:
        res_check = requests.get(f"{FIREBASE_URL}/movies/{tmdb_id}.json", timeout=5)
        if res_check.status_code == 200 and res_check.json():
            data = res_check.json()
            if data.get("url_720p") or data.get("url_1080p") or data.get("stream_url"): 
                print(f"⏭️ [BOT {BOT_ID}] PRE-CHECK SKIPPED: '{clean_name}' (Pehle se DB mein maujood hai)", flush=True)
                return 
    except: pass

    # 💡 MOVIE PAGE SE RESOLUTION PAGES DHUNDHNA
    resolution_pages = [] 
    for href, link_text in re.findall(r'<a\s+[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', m_resp.text, re.IGNORECASE | re.DOTALL):
        t_low = link_text.lower()
        h_low = href.lower()
        
        res = None
        if "1080p" in t_low or "1080p" in h_low: res = "1080p"
        elif "720p" in t_low or "720p" in h_low: res = "720p"
        elif "480p" in t_low or "300mb" in t_low or "480p" in h_low: res = "480p"
        
        if res and (".html" in h_low or "/movie/" in h_low):
            full_link = urllib.parse.urljoin(BASE_DOMAIN, href)
            resolution_pages.append((res, full_link))

    # Sirf unique resolution pages rakhne ke liye
    unique_res_pages = {}
    for res, link in resolution_pages:
        if res not in unique_res_pages:
            unique_res_pages[res] = link
            
    if not unique_res_pages: 
        print(f"⚠️ [BOT {BOT_ID}] SKIPPED: '{clean_name}' (Download page nahi mila)", flush=True)
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
        "hindi_dubbed": True, "category": f"Bollywood {release_year}",
        "is_series": False
    }

    # Har resolution (480p, 720p) ke page par ja kar server hunt karega
    for res_label, res_page_url in unique_res_pages.items():
        print(f"📥 [BOT {BOT_ID}] ENTERING {res_label} PAGE: {t_name}...", flush=True)
        server_links = get_server_links(res_page_url)
        
        if server_links:
            f_path = hit_and_trial_download(server_links, wd, res_page_url, BOT_ID, res_label, meta['title'])
            if f_path: 
                upload_and_sync(meta, tmdb_id, ident, res_label, f_path, BOT_ID)
        else:
            print(f"⚠️ [BOT {BOT_ID}] No servers found on {res_label} page.", flush=True)

    shutil.rmtree(wd, ignore_errors=True)

def run_bot():
    print(f"🔥 Starting Bot ID: {BOT_ID} (Duty: 20{27-BOT_ID}) - Account #{actual_bot_account_id}", flush=True)

    movie_links = get_strict_movies_for_bot()
    print(f"🎯 [BOT {BOT_ID}] Found {len(movie_links)} targets. Initiating Downloads...", flush=True)

    start_time = time.time()
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_CONCURRENT_TASKS) as executor:
        futures = []
        for m_url in movie_links[:MAX_MOVIES_PER_RUN]:
            if (time.time() - start_time) > 20000: break # GitHub Time Limit Protector
            futures.append(executor.submit(process_single_content, m_url))
        
        concurrent.futures.wait(futures)
        
    print(f"🏁 [BOT {BOT_ID}] FACTORY RUN COMPLETE!", flush=True)

if __name__ == "__main__":
    run_bot()
