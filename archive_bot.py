import os
import sys
import time
import json
import shutil
import re
import requests
import subprocess
import concurrent.futures
import internetarchive as ia

TMDB_API_KEY = "7b6a89d3dc55b3a81aa892a88c0da6b9"
FIREBASE_URL = "https://sijjmoviehub-default-rtdb.firebaseio.com"

BOT_ID = int(os.getenv("BOT_ID", "1"))
YEAR_START = int(os.getenv("YEAR_START", "2025"))
YEAR_END = int(os.getenv("YEAR_END", "2026"))
IA_ACCESS = os.getenv("IA_ACCESS", "").strip()
IA_SECRET = os.getenv("IA_SECRET", "").strip()

MAX_MOVIES_PER_RUN = 20  # Ab limit barha di hai kyunki bot slow movies ko instantly drop kar dega
MAX_PARALLEL_WORKERS = 3 # Ek sath 3 movies chalengi taake GitHub server par zyada load na pade

TRACKERS = (
    "udp://tracker.opentrackr.org:1337/announce,"
    "udp://open.demonii.com:1337/announce,"
    "udp://tracker.openbittorrent.com:6969/announce,"
    "udp://exodus.desync.com:6969/announce,"
    "udp://tracker.torrent.eu.org:451/announce"
)

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

def get_imdb_and_hindi_status(tmdb_id):
    imdb_id, has_hindi = None, False
    try:
        ext = requests.get(f"https://api.themoviedb.org/3/movie/{tmdb_id}/external_ids?api_key={TMDB_API_KEY}", timeout=10).json()
        imdb_id = ext.get("imdb_id")
        trans = requests.get(f"https://api.themoviedb.org/3/movie/{tmdb_id}/translations?api_key={TMDB_API_KEY}", timeout=10).json()
        has_hindi = any(t.get("iso_639_1") == "hi" for t in trans.get("translations", []))
    except Exception:
        pass
    return imdb_id, has_hindi

def fetch_fast_magnets(imdb_id):
    if not imdb_id: return []
    url = f"https://torrentio.strem.fun/stream/movie/{imdb_id}.json"
    magnets = []
    try:
        res = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        if res.status_code == 200:
            for s in res.json().get("streams", []):
                title_info = s.get("title", "").lower()
                # Reject giant packs to save server space
                if any(w in title_info for w in ["collection", "pack", "movies", "anthology", "complete", "season", "2160p", "4k"]):
                    continue
                info_hash = s.get("infoHash")
                if info_hash:
                    mag = f"magnet:?xt=urn:btih:{info_hash}&tr=" + TRACKERS.replace(",", "&tr=")
                    if "hindi" in title_info or "dual" in title_info or "multi" in title_info:
                        magnets.insert(0, mag)
                    elif "720p" in title_info or "1080p" in title_info:
                        magnets.append(mag)
    except Exception:
        pass
    return magnets[:3] # Top 3 fast links

def verify_video_file(filepath):
    if not os.path.exists(filepath): return False
    size_mb = os.path.getsize(filepath) / (1024 * 1024)
    if size_mb < 300 or size_mb > 5000: return False
    try:
        cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", filepath]
        output = subprocess.check_output(cmd, stderr=subprocess.STDOUT).decode().strip()
        return (float(output) / 60.0) >= 35.0
    except Exception:
        return False

def find_largest_video(folder):
    best_file, best_size = None, 0
    for root, _, files in os.walk(folder):
        for f in files:
            if f.lower().endswith((".mp4", ".mkv", ".avi")):
                fp = os.path.join(root, f)
                sz = os.path.getsize(fp)
                if sz > best_size:
                    best_size, best_file = sz, fp
    return best_file

def upload_to_archive_and_sync(meta, video_path):
    tmdb_id = str(meta["id"])
    movie_title_clean = clean_filename(meta["title"])
    release_year = meta.get("release_date", "2026")[:4]
    
    ext = os.path.splitext(video_path)[1].lower()
    cf = f"{movie_title_clean}_{release_year}_{tmdb_id}{ext}"
    ident = f"sijjhub-media-{tmdb_id}-{int(time.time())}"
    
    tp = os.path.join(os.path.dirname(video_path), cf)
    os.rename(video_path, tp)

    print(f"Uploading {cf} to Archive.org...")
    r = ia.upload(ident, files=[tp], metadata={"title": f"{meta['title']} ({release_year})", "mediatype": "movies"}, access_key=IA_ACCESS, secret_key=IA_SECRET)
    
    if r and r[0].status_code == 200:
        url = f"https://archive.org/download/{ident}/{cf}"
        meta.update({
            "stream_url": url, 
            "terabox_url": url, 
            "category": "Trending Hollywood (Hindi Dubbed)" if meta["hindi_dubbed"] else "Popular Updates"
        })
        requests.put(f"{FIREBASE_URL}/movies/{tmdb_id}.json", data=json.dumps(meta), timeout=15)
        return True
    return False

def process_single_movie(m):
    """Worker function: Ek single thread jo aik movie ko handle karega"""
    tmdb_id = str(m.get("id"))
    title = m.get("title", "Untitled")
    
    wd = f"/tmp/w_{BOT_ID}_{tmdb_id}"
    os.makedirs(wd, exist_ok=True)
    
    imdb, hindi = get_imdb_and_hindi_status(tmdb_id)
    magnets = fetch_fast_magnets(imdb)
    
    if not magnets:
        shutil.rmtree(wd, ignore_errors=True)
        return f"SKIP: No valid links for {title}"

    vp = None
    for mag in magnets:
        # Strict logic: 15s connection wait, minimum speed 1.5MB/s. Dropped instantly if slow!
        cmd = [
            "aria2c", 
            "--seed-time=0", 
            "--bt-stop-timeout=15", 
            "--lowest-speed-limit=1500K", 
            "--max-overall-download-limit=0", 
            "--max-tries=2", 
            "-d", wd, 
            mag
        ]
        try:
            # Maximum 5 mins wait per movie. Agar 5 min mein na ho toh timeout.
            subprocess.run(cmd, timeout=300)
            vf = find_largest_video(wd)
            if vf and verify_video_file(vf):
                vp = vf
                break # Movie fast download ho gayi, loop break karo
        except subprocess.TimeoutExpired:
            print(f"Timeout - {title} took too long.")
        except Exception:
            pass
        
        # Link fail hone par kachra saaf karo taake disk full na ho
        for f in os.listdir(wd):
            f_path = os.path.join(wd, f)
            if os.path.isfile(f_path): os.remove(f_path)

    if vp:
        meta = {
            "tmdb_id": tmdb_id, "id": tmdb_id, "title": title, 
            "overview": m.get("overview", ""), "release_date": m.get("release_date", ""), 
            "poster": f"https://image.tmdb.org/t/p/w500{m.get('poster_path')}" if m.get('poster_path') else "", 
            "hindi_dubbed": hindi or (m.get("original_language") == "hi")
        }
        success = upload_to_archive_and_sync(meta, vp)
        shutil.rmtree(wd, ignore_errors=True)
        if success:
            return f"SUCCESS: Downloaded & Synced {title}"
        return f"FAILED: Upload error for {title}"
        
    shutil.rmtree(wd, ignore_errors=True)
    return f"FAILED: Slow seeds - dropped {title}"

def run_bot():
    start_time = time.time()
    movies_to_process = []
    
    # 1. Pehle page se movies scan karo (MAX_MOVIES_PER_RUN tak)
    for page in range(1, 15):
        if len(movies_to_process) >= MAX_MOVIES_PER_RUN: break
        
        lang = "&with_original_language=hi" if (BOT_ID % 2 == 1) else ""
        url = f"https://api.themoviedb.org/3/discover/movie?api_key={TMDB_API_KEY}&sort_by=popularity.desc&primary_release_date.gte={YEAR_START}-01-01&primary_release_date.lte={YEAR_END}-12-31&page={page}{lang}"
        
        try:
            res = requests.get(url, timeout=15).json()
            for m in res.get("results", []):
                tmdb_id = str(m.get("id"))
                if not is_already_in_firebase(tmdb_id):
                    movies_to_process.append(m)
                if len(movies_to_process) >= MAX_MOVIES_PER_RUN: break
        except Exception as e:
            print(f"API fetch error: {e}")

    print(f"Ready to process {len(movies_to_process)} new movies in Parallel...")

    # 2. Multi-Threading shuru (3 movies aik waqt mein)
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_PARALLEL_WORKERS) as executor:
        futures = {executor.submit(process_single_movie, m): m for m in movies_to_process}
        
        for future in concurrent.futures.as_completed(futures):
            try:
                result = future.result()
                print(result)
            except Exception as e:
                print(f"Thread Error: {e}")
                
            # Har movie ke baad check karo ke 55 minutes (3300 seconds) cross toh nahi hue
            if (time.time() - start_time) > 3300:
                print("1 Hour Time limit approaching. Stopping gracefully...")
                # Cancel remaining tasks taake GitHub ban na kare
                executor.shutdown(wait=False, cancel_futures=True) 
                break

if __name__ == "__main__":
    run_bot()