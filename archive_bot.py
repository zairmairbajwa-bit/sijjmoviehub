import os
import time
import json
import re
import urllib.parse
import requests
import subprocess
import internetarchive as ia
import shutil

# === SECURE CREDENTIALS ===
TMDB_API_KEY = os.getenv("TMDB_API_KEY", "").strip() or "7b6a89d3dc55b3a81aa892a88c0da6b9"
FIREBASE_URL = os.getenv("FIREBASE_URL", "").strip() or "https://sijjmoviehub-default-rtdb.firebaseio.com"
BASE_DOMAIN = "https://www.filmyzilla82.com"

# 💡 TOTAL 8 BOTS (7 Background Workers + 1 Live On-Demand Bot)
BOT_ID = int(os.getenv("BOT_ID", "1") or "1")
TOTAL_BOTS = 8

actual_bot_account_id = ((BOT_ID - 1) % 4) + 1
IA_ACCESS = os.getenv(f"IA_ACCESS_{actual_bot_account_id}", "").strip()
IA_SECRET = os.getenv(f"IA_SECRET_{actual_bot_account_id}", "").strip()

MAX_MOVIES_PER_RUN = 5

# GLOBAL SESSION
session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Referer": BASE_DOMAIN
})

def clean_filename(name):
    cleaned = re.sub(r'[^a-zA-Z0-9_-]', '_', name)
    return re.sub(r'_+', '_', cleaned).strip('_')

# Purane ghalat/underscore wale links ko auto-fix karne ka function
def fix_existing_firebase_links():
    print("[MIGRATION] Checking database for old messy names to fix...")
    try:
        res = requests.get(f"{FIREBASE_URL}/movies.json", timeout=15)
        if res.status_code == 200 and res.json():
            movies_data = res.json()
            for tmdb_id, data in movies_data.items():
                if not isinstance(data, dict): continue
                title = data.get("title", "")
                release_year = str(data.get("release_date", "2026"))[:4]
                safe_title = clean_filename(title)
                
                updated = False
                for res_key in ["url_480p", "url_720p", "url_1080p", "stream_url"]:
                    link = data.get(res_key, "")
                    if link and "___________________" in link:
                        match = re.search(r'(sijjhub-media-\d+-\d+)', link)
                        if match:
                            ident = match.group(1)
                            res_label = res_key.replace("url_", "").replace("stream_", "1080p")
                            ext = ".mkv"
                            
                            new_cf = f"{safe_title}_{release_year}_{res_label}_{tmdb_id}{ext}"
                            new_link = f"https://archive.org/download/{ident}/{new_cf}"
                            
                            data[res_key] = new_link
                            updated = True
                
                if updated:
                    requests.put(f"{FIREBASE_URL}/movies/{tmdb_id}.json", data=json.dumps(data), timeout=10)
                    print(f"[MIGRATION] Fixed links for: {title} (ID: {tmdb_id})")
    except Exception as e:
        print(f"[MIGRATION] Error during auto-fix: {e}")

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

# 💡 1. TMDB PAGES SE FRESH MOVIES KE NAAM UTHANE KA FUNCTION (Har bot ke liye alag page range)
def fetch_movies_from_tmdb_pages(bot_id):
    movie_titles_to_search = []
    # Har bot TMDB ke alag-alag pages (jaise Bot 1 -> Pages 1-3, Bot 2 -> Pages 4-6...) target karega
    start_page = ((bot_id - 1) * 3) + 1
    end_page = start_page + 2
    
    print(f"[TMDB] Bot {bot_id} fetching movie titles from TMDB pages {start_page} to {end_page}...")
    
    for page in range(start_page, end_page + 1):
        url = f"https://api.themoviedb.org/3/movie/popular?api_key={TMDB_API_KEY}&language=hi&page={page}"
        try:
            res = requests.get(url, timeout=10)
            if res.status_code == 200:
                results = res.json().get("results", [])
                for item in results:
                    title = item.get("title") or item.get("name")
                    if title and title not in movie_titles_to_search:
                        movie_titles_to_search.append(title)
        except Exception as e:
            print(f"❌ TMDB Page fetch error: {e}")
            
    print(f"[TMDB] Collected {len(movie_titles_to_search)} titles from TMDB pages for Bot {bot_id}.")
    return movie_titles_to_search

# 💡 2. FILMYZILLA PAR TMDB KE NAAM SE SEARCH KARNE KA FUNCTION
def search_on_filmyzilla(movie_title):
    clean_query = re.sub(r'[^a-zA-Z0-9\s]', '', movie_title).strip()
    search_url = f"{BASE_DOMAIN}/search.html?q={urllib.parse.quote(clean_query)}"
    print(f"[FILMYZILLA] Searching for: '{clean_query}' -> {search_url}")
    
    try:
        session.headers.update({"Referer": BASE_DOMAIN})
        resp = session.get(search_url, timeout=20)
        if resp.status_code == 200:
            movie_pages = []
            hrefs = re.findall(r'href=["\'](.*?)["\']', resp.text)
            for href in hrefs:
                abs_url = urllib.parse.urljoin(BASE_DOMAIN, href)
                if "/movie/" in abs_url and abs_url.endswith(".html"):
                    if abs_url not in movie_pages:
                        movie_pages.append(abs_url)
            if movie_pages:
                print(f"[FILMYZILLA] Found matching page: {movie_pages[0]}")
                return movie_pages[0]
    except Exception as e:
        print(f"❌ FilmyZilla search error: {e}")
    return None

# 💡 3. SEQUENTIAL PIPELINE WITH CLEAR LOGGING
def upload_single_file_and_sync(meta, tmdb_id, release_year, ident, res_label, f_path):
    ext = os.path.splitext(f_path)[1].lower()
    if ext not in [".mp4", ".mkv"]: ext = ".mp4" 
    
    safe_title = clean_filename(meta['title'])
    cf = f"{safe_title}_{release_year}_{res_label}_{tmdb_id}{ext}"
    tp = os.path.join(os.path.dirname(f_path), cf)
    
    if f_path != tp:
        shutil.move(f_path, tp)
        
    print(f"🚀 [UPLOAD START] Uploading {res_label} file to Archive.org (Account #{actual_bot_account_id})...")
    time.sleep(BOT_ID * 2) 
    
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
            
            requests.put(f"{FIREBASE_URL}/movies/{tmdb_id}.json", data=json.dumps(meta), timeout=15)
            print(f"✅ [SUCCESS] {res_label} Successfully Uploaded to Archive.org and Synced to Firebase Database! Link: {archive_link}")
            
            try:
                os.remove(tp)
            except: pass
            
            time.sleep(5)
            return True
        else:
            print(f"❌ [FAILED] Archive.org Upload Failed for {res_label}!")
            try:
                os.remove(tp)
            except: pass
            return False
            
    except Exception as e:
        print(f"❌ [ERROR] CRITICAL ERROR during Archive.org Upload for {res_label}: {e}")
        try:
            os.remove(tp)
        except: pass
        return False

def download_with_aria2(url, work_dir, referer_url):
    print(f"📥 [ARIA2C] Downloading Video File at High Speed -> {url}")
    cmd = [
        "aria2c", "--dir=" + work_dir, "--seed-time=0", 
        "-x", "4", "-s", "4", "-j", "4", 
        "-c", "--max-tries=5", "--retry-wait=2", 
        "--min-split-size=10M",
        "--content-disposition-default-utf8=true", f"--referer={referer_url}",
        "--header=User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        url
    ]
    
    for attempt in range(1, 4):
        try:
            subprocess.run(cmd, check=True, timeout=7200)
            break
        except subprocess.CalledProcessError:
            time.sleep(3)
        except Exception:
            break
            
    for root, dirs, files in os.walk(work_dir):
        for file in files:
            if file.lower().endswith((".mp4", ".mkv")) and not file.endswith(".aria2"):
                return os.path.join(root, file)
                
    return None

def run_bot():
    print(f"🚀 Starting TMDB-Driven 8-Bot Cluster - Bot ID: {BOT_ID} (Account #{actual_bot_account_id})")
    
    if BOT_ID == 1:
        fix_existing_firebase_links()
        
    # 💡 BOT 8 IS RESERVED AS FREE ON-DEMAND WATCHER FOR USER REQUESTS
    if BOT_ID == 8:
        print("🤖 Bot 8 is running in Live On-Demand Watcher mode for app users...")
        time.sleep(10)
        return

    completed = 0
    start_time = time.time()
    
    # Get movie titles from TMDB pages assigned to this bot
    tmdb_titles = fetch_movies_from_tmdb_pages(BOT_ID)

    for title_query in tmdb_titles:
        if completed >= MAX_MOVIES_PER_RUN or (time.time() - start_time) > 20000: break 

        print(f"\n🔍 Searching FilmyZilla for TMDB title: '{title_query}'")
        m_url = search_on_filmyzilla(title_query)
        if not m_url: continue

        print(f"🎬 Processing Movie Page -> {m_url}")
        try:
            session.headers.update({"Referer": BASE_DOMAIN})
            m_resp = session.get(m_url, timeout=25)
        except Exception: continue
        
        title_match = re.search(r'<title>(.*?)</title>', m_resp.text, re.IGNORECASE)
        raw_title = title_match.group(1) if title_match else title_query
        
        # Verify with TMDB details
        url_tmdb = f"https://api.themoviedb.org/3/search/multi?api_key={TMDB_API_KEY}&query={urllib.parse.quote(title_query)}&language=hi"
        try:
            t_res = requests.get(url_tmdb, timeout=10).json().get("results", [])
            valid = [r for r in t_res if r.get("media_type") in ["movie", "tv"]]
            if not valid: continue
            tmdb_data = valid[0]
        except: continue
            
        tmdb_id = str(tmdb_data["id"])
        if is_fully_in_firebase(tmdb_id):
            print(f"⏩ Movie ID {tmdb_id} already fully saved in Firebase. Skipping...")
            continue
        
        res_links = {}
        m_hrefs = re.findall(r'<a\s+[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', m_resp.text, re.IGNORECASE | re.DOTALL)
        for href, text in m_hrefs:
            t_low = text.lower()
            if "480p" in t_low: res_links["480p"] = urllib.parse.urljoin(BASE_DOMAIN, href)
            elif "720p" in t_low: res_links["720p"] = urllib.parse.urljoin(BASE_DOMAIN, href)
            elif "1080p" in t_low: res_links["1080p"] = urllib.parse.urljoin(BASE_DOMAIN, href)

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
            "hindi_dubbed": True, "category": "Trending Hollywood & Bollywood"
        }

        # 💡 SEQUENTIAL RESOLUTION PIPELINE
        for res_label, resolution_page_url in res_links.items():
            print(f"⚙️ Processing Resolution {res_label} -> {resolution_page_url}")
            try:
                session.headers.update({"Referer": m_url})
                res_resp = session.get(resolution_page_url, timeout=25)
                
                server_url = None
                matches = re.finditer(r'<a\s+[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', res_resp.text, re.IGNORECASE | re.DOTALL)
                
                available_servers = {}
                for match in matches:
                    href = match.group(1)
                    clean_text = re.sub(r'<[^>]+>', ' ', match.group(2)).replace('\n', ' ').strip().lower()
                    if 'server 4' in clean_text: available_servers[4] = href
                    elif 'server 3' in clean_text: available_servers[3] = href
                    elif 'server 6' in clean_text: available_servers[6] = href
                    elif 'server 5' in clean_text: available_servers[5] = href
                    elif 'server 2' in clean_text: available_servers[2] = href
                    elif 'server 1' in clean_text: available_servers[1] = href
                
                for s_num in [4, 3, 6, 5, 2, 1]:
                    if s_num in available_servers:
                        server_url = urllib.parse.urljoin(resolution_page_url, available_servers[s_num])
                        break
                        
                if server_url:
                    session.headers.update({"Referer": resolution_page_url})
                    final_page_resp = session.get(server_url, timeout=30, stream=True)
                    real_mkv_url = final_page_resp.url 
                    final_page_resp.close() 
                    
                    if real_mkv_url:
                        f_path = download_with_aria2(real_mkv_url, wd, final_page_resp.url)
                        if f_path: 
                            upload_single_file_and_sync(meta, tmdb_id, release_year, ident, res_label, f_path)
                    
                    time.sleep(2) 
            except Exception as e:
                print(f"❌ Failed step for {res_label}: {e}")

        completed += 1
        shutil.rmtree(wd, ignore_errors=True)

    print("Bot run completed successfully.")

if __name__ == "__main__":
    run_bot()
