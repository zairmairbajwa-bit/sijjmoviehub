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

# 🚀 BUMPER SPEED UPGRADE: 5 se barha kar 25 movies per run kar di hain! (8 Bots x 25 = 200 Movies in one go)
MAX_MOVIES_PER_RUN = 25

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Referer": BASE_DOMAIN
})

def clean_filename(name):
    cleaned = re.sub(r'[^a-zA-Z0-9_-]', '_', name)
    return re.sub(r'_+', '_', cleaned).strip('_')

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

# 💡 STRICT YEAR ALLOCATION (Bot 1=2026, Bot 2=2025...)
def fetch_movies_from_tmdb_pages(bot_id):
    movie_titles_to_search = []
    target_year = 2027 - bot_id 
    
    print(f"📌 [BOT {bot_id}] Assigned STRICT YEAR: {target_year} for MAXIMUM Content!")
    
    # Ab zyada movies uthane ke liye top 5 pages se data layega
    for page in range(1, 6):
        url = f"https://api.themoviedb.org/3/discover/movie?api_key={TMDB_API_KEY}&language=hi&primary_release_year={target_year}&sort_by=popularity.desc&page={page}"
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
            
    print(f"📌 [BOT {bot_id}] Ready to hunt {len(movie_titles_to_search)} movies from Year {target_year}!")
    random.shuffle(movie_titles_to_search)
    return movie_titles_to_search

def search_on_filmyzilla(movie_title, bot_id):
    clean_query = re.sub(r'[^a-zA-Z0-9\s]', '', movie_title).strip()
    search_url = f"{BASE_DOMAIN}/search.html?q={urllib.parse.quote(clean_query)}"
    
    try:
        session.headers.update({"Referer": BASE_DOMAIN})
        resp = session.get(search_url, timeout=20)
        if resp.status_code == 200:
            query_words = clean_query.lower().split()
            matches = re.finditer(r'<a\s+[^>]*href=["\']([^"\']+/movie/[^"\']+\.html)["\'][^>]*>(.*?)</a>', resp.text, re.IGNORECASE)
            
            for match in matches:
                href = match.group(1)
                link_text = re.sub(r'<[^>]+>', ' ', match.group(2)).strip().lower()
                
                if query_words and (query_words[0] in link_text or query_words[0] in href.lower()):
                    abs_url = urllib.parse.urljoin(BASE_DOMAIN, href)
                    print(f"🎯 [BOT {bot_id}] TARGET LOCKED: {abs_url}")
                    return abs_url
    except Exception:
        pass
    print(f"⚠️ [BOT {bot_id}] Movie skipped (Not found): {movie_title}")
    return None

def upload_and_sync(meta, tmdb_id, release_year, ident, res_label, f_path, bot_id):
    ext = os.path.splitext(f_path)[1].lower()
    if ext not in [".mp4", ".mkv"]: ext = ".mp4" 
    
    safe_title = clean_filename(meta['title'])
    cf = f"{safe_title}_{release_year}_{res_label}_{tmdb_id}{ext}"
    tp = os.path.join(os.path.dirname(f_path), cf)
    
    if f_path != tp:
        shutil.move(f_path, tp)
        
    print(f"🚀 [BOT {bot_id}] Uploading {res_label} to Archive.org (Size: {os.path.getsize(tp)/(1024*1024):.1f} MB)...")
    time.sleep(1) # Chota delay taake speed kam na ho
    
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
            
            print(f"\n🎉 ==================================================")
            print(f"✅ [BOT {bot_id}] MEGA SUCCESS: UPLOADED & SYNCED!")
            print(f"🎬 Movie: {meta['title']} [{res_label}]")
            print(f"==================================================\n")
            
            try: 
                os.remove(tp)
                print(f"🗑️ [BOT {bot_id}] DISK CLEARED: File deleted from GitHub server for next download!\n")
            except: 
                pass
                
            return True
        else:
            print(f"❌ [BOT {bot_id}] Upload Failed!")
            try: os.remove(tp)
            except: pass
            return False
    except Exception as e:
        print(f"❌ [BOT {bot_id}] Error: {e}")
        try: os.remove(tp)
        except: pass
        return False

# 🚀 16 CONNECTIONS EXTREME HIGH-SPEED DOWNLOAD
def download_with_aria2(url, work_dir, referer_url, bot_id, res_label):
    print(f"📥 [BOT {bot_id}] Starting BEAST MODE Download (16 Threads) for {res_label}...")
    cmd = [
        "aria2c", "--dir=" + work_dir, "--seed-time=0", 
        "-x", "16", "-s", "16", "-j", "16",
        "-c", "--max-tries=5", "--retry-wait=2", 
        "--min-split-size=1M",
        "--content-disposition-default-utf8=true", f"--referer={referer_url}",
        "--header=User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        url
    ]
    
    try:
        subprocess.run(cmd, check=True, timeout=7200)
    except Exception as e:
        print(f"❌ [BOT {bot_id}] Download dropped: {e}")
        return None
            
    for root, dirs, files in os.walk(work_dir):
        for file in files:
            if file.lower().endswith((".mp4", ".mkv")) and not file.endswith(".aria2"):
                return os.path.join(root, file)
    return None

def run_bot():
    print(f"🔥 Starting BEAST MODE Bot ID: {BOT_ID} (Account #{actual_bot_account_id})")
        
    if BOT_ID == 8:
        print(f"🤖 [BOT 8] Live On-Demand Worker Ready...")
        time.sleep(10)
        return

    completed = 0
    start_time = time.time()
    
    tmdb_titles = fetch_movies_from_tmdb_pages(BOT_ID)

    for title_query in tmdb_titles:
        if completed >= MAX_MOVIES_PER_RUN or (time.time() - start_time) > 20000: 
            print(f"🏁 [BOT {BOT_ID}] Batch complete! Run successfully ended.")
            break 

        print(f"\n--------------------------------------------------")
        print(f"📋 [BOT {BOT_ID}] Hunting: '{title_query}'")

        url_tmdb = f"https://api.themoviedb.org/3/search/multi?api_key={TMDB_API_KEY}&query={urllib.parse.quote(title_query)}&language=hi"
        try:
            t_res = requests.get(url_tmdb, timeout=10).json().get("results", [])
            valid = [r for r in t_res if r.get("media_type") in ["movie", "tv"]]
            if not valid: continue
            tmdb_data = valid[0]
        except: continue
            
        tmdb_id = str(tmdb_data["id"])
        
        if is_fully_in_firebase(tmdb_id):
            print(f"⏩ [BOT {BOT_ID}] Already full in Firebase! Skipping fast...")
            continue

        m_url = search_on_filmyzilla(title_query, BOT_ID)
        if not m_url: continue

        try:
            session.headers.update({"Referer": BASE_DOMAIN})
            m_resp = session.get(m_url, timeout=25)
        except: continue
        
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

        for res_label, resolution_page_url in res_links.items():
            print(f"\n⚙️ [BOT {BOT_ID}] Ripping {res_label}...")
            try:
                session.headers.update({"Referer": m_url})
                res_resp = session.get(resolution_page_url, timeout=25)
                
                server_url = None
                matches = re.finditer(r'<a\s+[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', res_resp.text, re.IGNORECASE | re.DOTALL)
                
                for match in matches:
                    href = match.group(1)
                    clean_text = re.sub(r'<[^>]+>', ' ', match.group(2)).replace('\n', ' ').strip().lower()
                    # Sirf fast servers utha raha hai ab
                    if any(s in clean_text for s in ['server 4', 'server 3', 'server 6']):
                        server_url = urllib.parse.urljoin(resolution_page_url, href)
                        break
                        
                if not server_url:
                    for match in matches:
                        href = match.group(1)
                        if 'server' in href.lower():
                            server_url = urllib.parse.urljoin(resolution_page_url, href)
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
                    
                    time.sleep(1) 
            except Exception as e:
                print(f"❌ [BOT {BOT_ID}] Resolution {res_label} skip kardi: {e}")

        completed += 1
        shutil.rmtree(wd, ignore_errors=True)
        print(f"✅ [BOT {BOT_ID}] BOOM! Movie Done! Moving to next...\n")

if __name__ == "__main__":
    run_bot()
