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
TMDB_API_KEY = os.getenv("TMDB_API_KEY", "7b6a89d3dc55b3a81aa892a88c0da6b9")
FIREBASE_URL = os.getenv("FIREBASE_URL", "https://sijjmoviehub-default-rtdb.firebaseio.com")
BASE_DOMAIN = "https://www.filmyzilla82.com"

BOT_ID = int(os.getenv("BOT_ID", "1"))

# 💡 FIX: Har bot apna apna secret uthayega (e.g. IA_ACCESS_1, IA_ACCESS_2)
IA_ACCESS = os.getenv(f"IA_ACCESS_{BOT_ID}", "").strip()
IA_SECRET = os.getenv(f"IA_SECRET_{BOT_ID}", "").strip()

MAX_MOVIES_PER_RUN = 3
TOTAL_BOTS = 4

# GLOBAL SESSION
session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Referer": BASE_DOMAIN
})

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
        pass
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
    
    # 💡 FIX: Try-Except taake bot crash na ho agar upload mein masla aaye
    try:
        r = ia.upload(
            ident, files=files_to_upload, 
            metadata={"title": f"{meta['title']} ({release_year})", "mediatype": "movies"}, 
            access_key=IA_ACCESS, secret_key=IA_SECRET
        )
        
        if r and r[0].status_code == 200:
            meta.update(firebase_links)
            meta["stream_url"] = firebase_links.get("url_720p") or firebase_links.get("url_480p") or firebase_links.get("url_1080p")
            meta["category"] = "Latest Updates"
            
            requests.put(f"{FIREBASE_URL}/movies/{tmdb_id}.json", data=json.dumps(meta), timeout=15)
            print(f"✅ Firebase sync successful!")
            return True
        else:
            print(f"❌ Archive.org Upload Failed! Status: {r[0].status_code if r else 'No Response'}")
            return False
            
    except Exception as e:
        print(f"❌ CRITICAL ERROR during Archive.org Upload: {e}")
        return False

def download_with_aria2(url, work_dir, referer_url):
    print(f"Step 5: Aria2c Downloading REAL Video File (Balanced Mode) -> {url}")
    # 4 connections taake speed achi mile aur ban na ho
    cmd = [
        "aria2c", "--dir=" + work_dir, "--seed-time=0", 
        "-x", "4", "-s", "4", "-j", "4", 
        "--min-split-size=10M",
        "--content-disposition-default-utf8=true", f"--referer={referer_url}",
        "--header=User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        url
    ]
    try:
        subprocess.run(cmd, check=True, timeout=7200) 
        for root, dirs, files in os.walk(work_dir):
            for file in files:
                if file.lower().endswith((".mp4", ".mkv")) and not file.endswith(".aria2"):
                    return os.path.join(root, file)
    except Exception as e:
        print(f"Aria2 download failed: {e}")
    return None

def run_bot():
    print(f"Starting Crash-Free Human Flow Bot ID: {BOT_ID}")
    completed = 0
    start_time = time.time()
    
    print(f"Step 1: Opening Home Page -> {BASE_DOMAIN}")
    try:
        resp = session.get(BASE_DOMAIN, timeout=25)
    except Exception as e:
        print(f"Home page fetch failed: {e}")
        return

    all_movie_pages = []
    hrefs = re.findall(r'href=["\'](.*?)["\']', resp.text)
    for href in hrefs:
        abs_url = urllib.parse.urljoin(BASE_DOMAIN, href)
        if "/movie/" in abs_url and abs_url.endswith(".html"):
            if abs_url not in all_movie_pages:
                all_movie_pages.append(abs_url)

    chunk_size = max(1, len(all_movie_pages) // TOTAL_BOTS) if all_movie_pages else 1
    start_idx = (BOT_ID - 1) * chunk_size
    end_idx = start_idx + chunk_size if BOT_ID < TOTAL_BOTS else len(all_movie_pages)
    my_movie_pages = all_movie_pages[start_idx:end_idx] if all_movie_pages else []
    print(f"Bot {BOT_ID} assigned {len(my_movie_pages)} movies.")

    for m_url in my_movie_pages:
        if completed >= MAX_MOVIES_PER_RUN or (time.time() - start_time) > 20000: break 

        print(f"\nStep 2: Clicking on Movie -> {m_url}")
        try:
            session.headers.update({"Referer": BASE_DOMAIN})
            m_resp = session.get(m_url, timeout=25)
        except Exception: continue
        
        title_match = re.search(r'<title>(.*?)</title>', m_resp.text, re.IGNORECASE)
        raw_title = title_match.group(1) if title_match else "Unknown"
        
        tmdb_data = search_tmdb_from_title(raw_title)
        if not tmdb_data: continue
            
        tmdb_id = str(tmdb_data["id"])
        if is_fully_in_firebase(tmdb_id):
            print(f"Movie pehle se Firebase me hai. Next...")
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
        downloaded_paths = {}

        for res_label, resolution_page_url in res_links.items():
            print(f"Step 3: Clicking on Resolution {res_label} -> {resolution_page_url}")
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
                        print(f"--> Found 'Server {s_num}' button! Redirect Link: {server_url}")
                        break
                        
                if server_url:
                    print(f"Step 4: Opening Redirect Page to extract actual file...")
                    session.headers.update({"Referer": resolution_page_url})
                    
                    final_page_resp = session.get(server_url, timeout=30, stream=True)
                    real_mkv_url = final_page_resp.url 
                    final_page_resp.close() 
                    
                    if real_mkv_url:
                        print(f"--> Success! Found Real Video Link: {real_mkv_url}")
                        f_path = download_with_aria2(real_mkv_url, wd, final_page_resp.url)
                        if f_path: downloaded_paths[res_label] = f_path
                    
                    time.sleep(2) 
                else:
                    print(f"❌ ERROR: Is page par red server buttons nahi milay!")
                    
            except Exception as e:
                print(f"❌ Failed download step for {res_label}: {e}")

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
                print(f"✅ Movie Uploaded & Synced Successfully!")
                
        shutil.rmtree(wd, ignore_errors=True)

    print("Bot run completed.")

if __name__ == "__main__":
    run_bot()
