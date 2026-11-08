import os
import time
import json
import shutil
import re
import requests
import subprocess
import internetarchive as ia

# === APKI API KEYS ===
TMDB_API_KEY = "7b6a89d3dc55b3a81aa892a88c0da6b9"
FIREBASE_URL = "https://sijjmoviehub-default-rtdb.firebaseio.com"

# === BOT SETTINGS ===
BOT_ID = int(os.getenv("BOT_ID", "1"))
YEAR_START = int(os.getenv("YEAR_START", "2025"))
YEAR_END = int(os.getenv("YEAR_END", "2026"))
IA_ACCESS = os.getenv("IA_ACCESS", "").strip()
IA_SECRET = os.getenv("IA_SECRET", "").strip()

MAX_MOVIES_PER_RUN = 3

def clean_filename(name):
    return re.sub(r'[^a-zA-Z0-9_-]', '_', name)

def is_already_in_firebase(tmdb_id):
    try:
        res = requests.get(f"{FIREBASE_URL}/movies/{tmdb_id}.json", timeout=10)
        if res.status_code == 200 and res.json():
            data = res.json()
            if "archive.org/download/" in data.get("stream_url", ""):
                return True
    except Exception:
        pass
    return False

def get_imdb_id(tmdb_id):
    try:
        ext = requests.get(f"https://api.themoviedb.org/3/movie/{tmdb_id}/external_ids?api_key={TMDB_API_KEY}", timeout=10).json()
        return ext.get("imdb_id")
    except:
        return None

def upload_to_archive_and_sync(meta, video_path):
    tmdb_id = str(meta["id"])
    movie_title_clean = clean_filename(meta["title"])
    release_year = meta.get("release_date", "2026")[:4]
    
    ext = os.path.splitext(video_path)[1].lower()
    if not ext: ext = ".mp4"
    
    cf = f"{movie_title_clean}_{release_year}_{tmdb_id}{ext}"
    ident = f"sijjhub-media-{tmdb_id}-{int(time.time())}"
    
    tp = os.path.join(os.path.dirname(video_path), cf)
    os.rename(video_path, tp)

    print(f"Uploading {cf} to Archive.org under your account...")
    r = ia.upload(
        ident, 
        files=[tp], 
        metadata={"title": f"{meta['title']} ({release_year})", "mediatype": "movies"}, 
        access_key=IA_ACCESS, 
        secret_key=IA_SECRET
    )
    
    if r and r[0].status_code == 200:
        url = f"https://archive.org/download/{ident}/{cf}"
        meta.update({
            "stream_url": url, 
            "terabox_url": url, 
            "category": "Popular Updates"
        })
        requests.put(f"{FIREBASE_URL}/movies/{tmdb_id}.json", data=json.dumps(meta), timeout=15)
        return True
    return False

def download_with_aria2(url_or_torrent, work_dir):
    """Aria2c ko use karke Fast HTTP ya Torrent download karta hai"""
    print(f"Downloading with aria2c: {url_or_torrent}")
    cmd = [
        "aria2c",
        "--dir=" + work_dir,
        "--seed-time=0", # Seed nahi karna, sirf download
        "--summary-interval=60",
        url_or_torrent
    ]
    try:
        subprocess.run(cmd, check=True)
        # Downloaded file dhundo (mp4 ya mkv)
        for root, dirs, files in os.walk(work_dir):
            for file in files:
                if file.endswith((".mp4", ".mkv")):
                    return os.path.join(root, file)
    except Exception as e:
        print(f"Aria2 download failed: {e}")
    return None

def engine_1_archive_search(title, year, work_dir):
    """Archive.org par public movies search karke clone karta hai"""
    print(f"[ENGINE 1] Archive.org par '{title} {year}' search kar raha hai...")
    query = f"title:({title}) AND year:({year}) AND mediatype:(movies)"
    search = ia.search_items(query)
    
    for item in search:
        ident = item['identifier']
        details = ia.get_item(ident)
        for file in details.files:
            if file['name'].endswith((".mp4", ".mkv")):
                url = f"https://archive.org/download/{ident}/{file['name']}"
                print(f"Archive.org par file mil gayi! Cloning from: {url}")
                return download_with_aria2(url, work_dir)
    print("Archive.org par yeh movie nahi mili.")
    return None

def engine_2_torrent_search(imdb_id, work_dir):
    """Agar Archive par na mile toh YTS Torrent se download karta hai"""
    if not imdb_id: return None
    print(f"[ENGINE 2] YTS Torrent par '{imdb_id}' search kar raha hai...")
    try:
        res = requests.get(f"https://yts.mx/api/v2/movie_details.json?imdb_id={imdb_id}", timeout=10).json()
        if res.get("data", {}).get("movie"):
            torrents = res["data"]["movie"].get("torrents", [])
            for t in torrents:
                if t.get("quality") in ["720p", "1080p"]:
                    print(f"Torrent file mil gayi. Sabar ke sath downloading shuru...")
                    return download_with_aria2(t["url"], work_dir)
    except Exception as e:
        print(f"YTS API error: {e}")
    return None

def main():
    print(f"Starting SijjMoviesHub Hybrid Bot ID: {BOT_ID}")
    
    completed = 0
    start_time = time.time()
    
    # Har bot apne hisse ke pages check karega
    for page in range(BOT_ID, 50, 8):
        if completed >= MAX_MOVIES_PER_RUN: break
        if (time.time() - start_time) > 20000: # ~5.5 hours limit
            print("Time limit reached. Stopping gracefully.")
            break 

        # TMDB API url
        url = f"https://api.themoviedb.org/3/discover/movie?api_key={TMDB_API_KEY}&sort_by=popularity.desc&primary_release_date.gte={YEAR_START}-01-01&primary_release_date.lte={YEAR_END}-12-31&page={page}&with_original_language=hi"
        
        try:
            res = requests.get(url, timeout=15).json()
            for m in res.get("results", []):
                if completed >= MAX_MOVIES_PER_RUN: break
                
                tmdb_id = str(m.get("id"))
                if is_already_in_firebase(tmdb_id): continue
                
                title = m.get("title", "Untitled")
                release_year = m.get("release_date", "2026")[:4]
                imdb_id = get_imdb_id(tmdb_id)
                
                wd = f"/tmp/w_{BOT_ID}_{tmdb_id}"
                os.makedirs(wd, exist_ok=True)
                
                # --- DOUBLE ENGINE LOGIC ---
                # Pehle Archive se clone karne ki koshish karega
                vp = engine_1_archive_search(title, release_year, wd)
                
                # Agar Archive se na mile, toh Torrent se uthayega
                if not vp:
                    vp = engine_2_torrent_search(imdb_id, wd)
                
                if vp:
                    meta = {
                        "tmdb_id": tmdb_id, "id": tmdb_id, "title": title, 
                        "overview": m.get("overview", ""), "release_date": m.get("release_date", ""), 
                        "poster": f"https://image.tmdb.org/t/p/w500{m.get('poster_path')}" if m.get('poster_path') else "", 
                        "hindi_dubbed": True # YTS + Hindi API = Original/Dubbed
                    }
                    if upload_to_archive_and_sync(meta, vp):
                        completed += 1
                        print(f"Successfully synced: {title}")
                        
                shutil.rmtree(wd, ignore_errors=True)
        except Exception as e:
            print(f"Run exception encountered: {e}")

    print("Bot run completed.")

if __name__ == "__main__":
    main()