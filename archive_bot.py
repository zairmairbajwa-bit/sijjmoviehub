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
BASE_DOMAIN = "https://www.filmyzilla82.com"

BOT_ID = int(os.getenv("BOT_ID", "1") or "1")
TOTAL_BOTS = 8

actual_bot_account_id = ((BOT_ID - 1) % 4) + 1
IA_ACCESS = os.getenv(f"IA_ACCESS_{actual_bot_account_id}", "").strip()
IA_SECRET = os.getenv(f"IA_SECRET_{actual_bot_account_id}", "").strip()

MAX_MOVIES_PER_RUN = 4

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Referer": BASE_DOMAIN
})

def clean_filename(name):
    cleaned = re.sub(r'[^a-zA-Z0-9_-]', '_', name)
    return re.sub(r'_+', '_', cleaned).strip('_')

def fix_existing_firebase_links():
    print("[MIGRATION] Checking database for old messy names...")
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
                for res_key in ["url_720p", "url_1080p", "url_480p", "stream_url"]:
                    link = data.get(res_key, "")
                    if link and "___________________" in link:
                        match = re.search(r'(sijjhub-media-\d+-\d+)', link)
                        if match:
                            ident = match.group(1)
                            res_lbl = res_key.replace("url_", "").replace("stream_", "1080p")
                            ext = ".mp4"
                            new_cf = f"{safe_title}_{release_year}_{res_lbl}_{tmdb_id}{ext}"
                            new_link = f"https://archive.org/download/{ident}/{new_cf}"
                            data[res_key] = new_link
                            updated = True
                if updated:
                    requests.put(f"{FIREBASE_URL}/movies/{tmdb_id}.json", data=json.dumps(data), timeout=10)
    except Exception as e:
        print(f"[MIGRATION] Error: {e}")

def is_fully_in_firebase(tmdb_id):
    try:
        res = requests.get(f"{FIREBASE_URL}/movies/{tmdb_id}.json", timeout=10)
        if res.status_code == 200 and res.json():
            data = res.json()
            if data.get("url_480p") and data.get("url_720p") and data.get("url_1080p"):
                return True
    except:
        pass
    return False

# 💡 STRICT NON-OVERLAPPING TMDB PAGES ALLOCATION FOR 8 BOTS
def fetch_movies_from_tmdb_pages(bot_id):
    movie_titles_to_search = []
    # Har bot ke liye bilkul alag page (Bot 1 -> Page 1, Bot 2 -> Page 2, etc. + random offset)
    target_page = bot_id + random.randint(0, 5) * 8
    
    print(f"📌 [BOT {bot_id}] Assigned TMDB Discover Page Number: {target_page}")
    
    url = f"https://api.themoviedb.org/3/discover/movie?api_key={TMDB_API_KEY}&language=hi&sort_by=popularity.desc&page={target_page}"
    try:
        res = requests.get(url, timeout=10)
        if res.status_code == 200:
            results = res.json().get("results", [])
            for item in results:
                title = item.get("title") or item.get("name")
                if title and title not in movie_titles_to_search:
                    movie_titles_to_search.append(title)
    except Exception as e:
        print(f"❌ [BOT {bot_id}] TMDB Error: {e}")
        
    print(f"📌 [BOT {bot_id}] Fetched {len(movie_titles_to_search)} movie titles from TMDB page {target_page}.")
    random.shuffle(movie_titles_to_search)
    return movie_titles_to_search

def search_on_filmyzilla(movie_title, bot_id):
    clean_query = re.sub(r'[^a-zA-Z0-9\s]', '', movie_title).strip()
    search_url = f"{BASE_DOMAIN}/search.html?q={urllib.parse.quote(clean_query)}"
    print(f"🔎 [BOT {bot_id}] Searching FilmyZilla for Name: '{clean_query}' -> URL: {search_url}")
    
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
                print(f"🎯 [BOT {bot_id}] Movie found on FilmyZilla page: {movie_pages[0]}")
                return movie_pages[0]
    except Exception as e:
        print(f"❌ [BOT {bot_id}] FilmyZilla Search error: {e}")
    print(f"⚠️ [BOT {bot_id}] Movie NOT found on FilmyZilla: {movie_title}")
    return None

def upload_and_sync(meta, tmdb_id, release_year, ident, res_label, f_path, bot_id):
    ext = os.path.splitext(f_path)[1].lower()
    if ext not in [".mp4", ".mkv"]: ext = ".mp4" 
    
    safe_title = clean_filename(meta['title'])
    cf = f"{safe_title}_{release_year}_{res_label}_{tmdb_id}{ext}"
    tp = os.path.join(os.path.dirname(f_path), cf)
    
    if f_path != tp:
        shutil.move(f_path, tp)
        
    print(f"🚀 [BOT {bot_id}] Uploading {res_label} file to Archive.org (Account #{actual_bot_account_id})...")
    time.sleep(bot_id * 2) 
    
    try:
        r = ia.upload(
            ident, files=[tp], 
            metadata={"title": f"{meta['title']} ({release_year})", "mediatype": "movies"}, 
            access_key=IA_ACCESS, secret_key=IA_SECRET
        )
        
        if r and r[0].status_code == 200:
            archive_link = f"https://archive.org/download/{ident}/{cf}"
            meta[f"url_{res_label}"] = archive_link
            meta["stream_url"] = archive_link # Default stream
            
            requests.put(f"{FIREBASE_URL}/movies/{tmdb_id}.json", data=json.dumps(meta), timeout=15)
            print(f"\n🎉 ==================================================")
            print(f"✅ [BOT {bot_id}] UPLOADED & SYNCED SUCCESSFULLY!")
            print(f"🎬 Movie Name: {meta['title']} [{res_label}]")
            print(f"🔗 Archive Link: {archive_link}")
            print(f"==================================================\n")
            
            try: os.remove(tp)
            except: pass
            return True
        else:
            print(f"❌ [BOT {bot_id}] Archive Upload Failed for {res_label}!")
            try: os.remove(tp)
            except: pass
            return False
    except Exception as e:
        print(f"❌ [BOT {bot_id}] Upload Exception: {e}")
        try: os.remove(tp)
        except: pass
        return False

def download_with_aria2(url, work_dir, referer_url, bot_id, res_label):
    print(f"📥 [BOT {bot_id}] Downloading {res_label} using 4 connections (Aria2c) -> {url}")
    cmd = [
        "aria2c", "--dir=" + work_dir, "--seed-time=0", 
        "-x", "4", "-s", "4", "-j", "4",
        "-c", "--max-tries=5", "--retry-wait=3", 
        "--min-split-size=5M",
        "--content-disposition-default-utf8=true", f"--referer={referer_url}",
        "--header=User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        url
    ]
    
    try:
        subprocess.run(cmd, check=True, timeout=7200)
    except Exception as e:
        print(f"❌ [BOT {bot_id}] Download failed for {res_label}: {e}")
        return None
            
    for root, dirs, files in os.walk(work_dir):
        for file in files:
            if file.lower().endswith((".mp4", ".mkv")) and not file.endswith(".aria2"):
                return os.path.join(root, file)
    return None

def run_bot():
    print(f"🚀 Starting Detailed Track Bot ID: {BOT_ID} (Account #{actual_bot_account_id})")
    
    if BOT_ID == 1:
        fix_existing_firebase_links()
        
    if BOT_ID == 8:
        print(f"🤖 [BOT 8] Running in Live On-Demand Watcher mode...")
        time.sleep(10)
        return

    completed = 0
    start_time = time.time()
    
    tmdb_titles = fetch_movies_from_tmdb_pages(BOT_ID)

    for title_query in tmdb_titles:
        if completed >= MAX_MOVIES_PER_RUN or (time.time() - start_time) > 20000: break 

        print(f"\n--------------------------------------------------")
        print(f"📋 [BOT {BOT_ID}] Step 1: Picked Movie Name from TMDB Page: '{title_query}'")

        # Get TMDB details first
        url_tmdb = f"https://api.themoviedb.org/3/search/multi?api_key={TMDB_API_KEY}&query={urllib.parse.quote(title_query)}&language=hi"
        try:
            t_res = requests.get(url_tmdb, timeout=10).json().get("results", [])
            valid = [r for r in t_res if r.get("media_type") in ["movie", "tv"]]
            if not valid: continue
            tmdb_data = valid[0]
        except: continue
            
        tmdb_id = str(tmdb_data["id"])
        if is_fully_in_firebase(tmdb_id):
            print(f"⏩ [BOT {BOT_ID}] Movie ID {tmdb_id} already fully in Firebase with all resolutions. Skipping instantly...")
            continue

        # Step 2: Search on FilmyZilla
        m_url = search_on_filmyzilla(title_query, BOT_ID)
        if not m_url: continue

        print(f"🛠️ [BOT {BOT_ID}] Step 3: Opening FilmyZilla Movie Page -> {m_url}")
        try:
            session.headers.update({"Referer": BASE_DOMAIN})
            m_resp = session.get(m_url, timeout=25)
        except Exception: continue
        
        res_links = {}
        m_hrefs = re.findall(r'<a\s+[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', m_resp.text, re.IGNORECASE | re.DOTALL)
        for href, text in m_hrefs:
            t_low = text.lower()
            if "720p" in t_low: res_links["720p"] = urllib.parse.urljoin(BASE_DOMAIN, href)
            elif "1080p" in t_low: res_links["1080p"] = urllib.parse.urljoin(BASE_DOMAIN, href)
            elif "480p" in t_low: res_links["480p"] = urllib.parse.urljoin(BASE_DOMAIN, href)

        if not res_links: 
            print(f"⚠️ [BOT {BOT_ID}] No resolution links found on page.")
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

        # Step 4: Download & Upload All Available Resolutions One by One (480p, 720p, 1080p)
        for res_label, resolution_page_url in res_links.items():
            print(f"⚙️ [BOT {BOT_ID}] Step 4: Clicking and resolving {res_label} resolution page -> {resolution_page_url}")
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
                        print(f"🖱️ [BOT {BOT_ID}] Clicked Server {s_num} for {res_label}")
                        break
                        
                if server_url:
                    session.headers.update({"Referer": resolution_page_url})
                    final_page_resp = session.get(server_url, timeout=30, stream=True)
                    real_mkv_url = final_page_resp.url 
                    final_page_resp.close() 
                    
                    if real_mkv_url:
                        f_path = download_with_aria2(real_mkv_url, wd, final_page_resp.url, BOT_ID, res_label)
                        if f_path: 
                            upload_and_sync(meta, tmdb_id, release_year, ident, res_label, f_path, BOT_ID)
                    
                    time.sleep(2) 
            except Exception as e:
                print(f"❌ [BOT {BOT_ID}] Failed resolution {res_label}: {e}")

        completed += 1
        shutil.rmtree(wd, ignore_errors=True)
        print(f"✅ [BOT {BOT_ID}] Completed movie processing. Moving to next movie...\n")

    print(f"🏁 [BOT {BOT_ID}] Bot run completed successfully.")

if __name__ == "__main__":
    run_bot()
