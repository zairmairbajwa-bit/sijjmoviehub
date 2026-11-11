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

# 💡 NAYA DOMAIN
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

def get_firebase_movie_data(tmdb_id):
    try:
        res = requests.get(f"{FIREBASE_URL}/movies/{tmdb_id}.json", timeout=10)
        if res.status_code == 200 and res.json():
            return res.json()
    except: pass
    return None

# 💡 BOTS KA KAAM BANT DIYA GAYA HAI (TMDB YEAR DIVISION)
def fetch_movies_from_tmdb_pages(bot_id):
    movie_titles_to_search = []
    # Bot 1 -> 2026, Bot 2 -> 2025, Bot 3 -> 2024 ...
    target_year = 2027 - bot_id 
    
    print(f"📌 [BOT {bot_id}] Assigned TMDB YEAR: {target_year} for MAXIMUM Content!")
    
    for page in range(1, 6): # Top 5 pages uthayega
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
            
    print(f"📌 [BOT {bot_id}] Ready to search {len(movie_titles_to_search)} movies from Year {target_year} on Filmicity!")
    random.shuffle(movie_titles_to_search)
    return movie_titles_to_search

# 💡 WEBSITE PAR DIRECT SEARCH FUNCTION
def search_on_filmicity(movie_title, bot_id):
    clean_query = re.sub(r'[^a-zA-Z0-9\s]', '', movie_title).strip()
    search_url = f"{BASE_DOMAIN}/search.html?q={urllib.parse.quote(clean_query)}"
    print(f"🔎 [BOT {bot_id}] Searching '{clean_query}' on Filmicity Search Bar...")
    
    try:
        session.headers.update({"Referer": BASE_DOMAIN})
        resp = session.get(search_url, timeout=20)
        if resp.status_code == 200:
            query_words = clean_query.lower().split()
            matches = re.finditer(r'<a\s+[^>]*href=["\']([^"\']+\.html)["\'][^>]*>(.*?)</a>', resp.text, re.IGNORECASE)
            
            for match in matches:
                href = match.group(1)
                link_text = re.sub(r'<[^>]+>', ' ', match.group(2)).strip().lower()
                
                # Check if search term matches the result
                if query_words and (query_words[0] in link_text or query_words[0] in href.lower()):
                    if "category" not in href.lower(): # Only pick actual movies
                        abs_url = urllib.parse.urljoin(BASE_DOMAIN, href)
                        print(f"🎯 [BOT {bot_id}] Search Match Found: {abs_url}")
                        return abs_url
    except Exception:
        pass
    print(f"⚠️ [BOT {bot_id}] Movie not found on website: {movie_title}")
    return None

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

# 💡 HIGH-SPEED ARIA2 DIRECT DOWNLOAD
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
    print(f"🔥 Starting TMDB->SEARCH Bot ID: {BOT_ID} (Account #{actual_bot_account_id})")
        
    if BOT_ID == 8:
        print(f"🤖 [BOT 8] Live Worker is on Standby for App Users...")
        time.sleep(10)
        return

    completed = 0
    start_time = time.time()
    
    # 1. TMDB se movies ki list uthana (Year-wise divided)
    tmdb_titles = fetch_movies_from_tmdb_pages(BOT_ID)

    for title_query in tmdb_titles:
        if completed >= MAX_MOVIES_PER_RUN or (time.time() - start_time) > 20000: break 

        print(f"\n--------------------------------------------------")
        print(f"🛠️ [BOT {BOT_ID}] Step 1: Processing TMDB Movie -> '{title_query}'")

        # TMDB data lena pre-check ke liye
        url_tmdb = f"https://api.themoviedb.org/3/search/multi?api_key={TMDB_API_KEY}&query={urllib.parse.quote(title_query)}&language=hi"
        try:
            t_res = requests.get(url_tmdb, timeout=10).json().get("results", [])
            valid = [r for r in t_res if r.get("media_type") in ["movie", "tv"]]
            if not valid: continue
            tmdb_data = valid[0]
        except: continue
            
        tmdb_id = str(tmdb_data["id"])
        
        # 2. Database check karna ke pehle toh nahi ki hui
        existing_db_movie = get_firebase_movie_data(tmdb_id)
        if existing_db_movie:
            if existing_db_movie.get("url_480p") and existing_db_movie.get("url_720p") and existing_db_movie.get("url_1080p"):
                print(f"⏩ [BOT {BOT_ID}] All resolutions exist in Firebase! Skipping...")
                continue

        # 3. Filmicity ki website par search marna
        m_url = search_on_filmicity(title_query, BOT_ID)
        if not m_url: continue

        print(f"✅ [BOT {BOT_ID}] Step 3: Extracting Direct Download Links from Page...")
        try:
            session.headers.update({"Referer": BASE_DOMAIN})
            m_resp = session.get(m_url, timeout=25)
        except: continue
        
        res_links = {}
        # Screen ke mutabiq direct "Download 470Mb {480p}" wale links pakarna
        m_hrefs = re.findall(r'<a\s+[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', m_resp.text, re.IGNORECASE | re.DOTALL)
        for href, text in m_hrefs:
            t_low = text.lower()
            if "download" in t_low:
                if "720p" in t_low: res_links["720p"] = urllib.parse.urljoin(BASE_DOMAIN, href)
                elif "1080p" in t_low: res_links["1080p"] = urllib.parse.urljoin(BASE_DOMAIN, href)
                elif "480p" in t_low: res_links["480p"] = urllib.parse.urljoin(BASE_DOMAIN, href)

        if not res_links: 
            print(f"⚠️ [BOT {BOT_ID}] No direct download links found on page.")
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

        # 💡 NAYA STEP 4: DIRECT DOWNLOAD (Seedha Aria2c ko link dena hai)
        for res_label, direct_download_url in res_links.items():
            
            if existing_db_movie and existing_db_movie.get(f"url_{res_label}"):
                print(f"⏩ [BOT {BOT_ID}] SKIPPING {res_label}: Already in Firebase!")
                continue
                
            print(f"\n⚙️ [BOT {BOT_ID}] Step 4: Initiating Direct Download for {res_label}...")
            try:
                # Seedha aria2 function ko link bhejo
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
