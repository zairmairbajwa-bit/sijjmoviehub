import os
import sys
import time
import json
import shutil
import requests
import subprocess
import internetarchive as ia
from bs4 import BeautifulSoup
import cloudscraper

TMDB_API_KEY = "7b6a89d3dc55b3a81aa892a88c0da6b9"
FIREBASE_URL = "https://sijjmoviehub-default-rtdb.firebaseio.com"

BOT_ID = int(os.getenv("BOT_ID", "1"))
YEAR_START = int(os.getenv("YEAR_START", "2025"))
YEAR_END = int(os.getenv("YEAR_END", "2026"))
IA_ACCESS = os.getenv("IA_ACCESS", "").strip()
IA_SECRET = os.getenv("IA_SECRET", "").strip()
MAX_MOVIES_PER_RUN = 12

TRACKERS = (
    "udp://tracker.opentrackr.org:1337/announce,"
    "udp://open.demonii.com:1337/announce,"
    "udp://tracker.openbittorrent.com:6969/announce,"
    "udp://exodus.desync.com:6969/announce,"
    "udp://tracker.torrent.eu.org:451/announce,"
    "http://tracker.openbittorrent.com:80/announce"
)

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

def fetch_magnets_from_torrentio(imdb_id):
    if not imdb_id: return []
    url = f"https://torrentio.strem.fun/stream/movie/{imdb_id}.json"
    magnets = []
    try:
        res = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        if res.status_code == 200:
            for s in res.json().get("streams", []):
                info_hash = s.get("infoHash")
                title_info = s.get("title", "").lower()
                if info_hash:
                    mag = f"magnet:?xt=urn:btih:{info_hash}&tr=" + TRACKERS.replace(",", "&tr=")
                    if "hindi" in title_info or "dual" in title_info or "multi" in title_info:
                        magnets.insert(0, mag)
                    elif "720p" in title_info or "1080p" in title_info:
                        magnets.append(mag)
    except Exception:
        pass
    return magnets[:3]

def verify_video_file(filepath):
    if not os.path.exists(filepath): return False
    size_mb = os.path.getsize(filepath) / (1024 * 1024)
    if size_mb < 300 or size_mb > 5000: return False
    try:
        cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", filepath]
        output = subprocess.check_output(cmd, stderr=subprocess.STDOUT).decode().strip()
        return (float(output) / 60.0) >= 40.0
    except Exception:
        return False

def find_largest_video(folder):
    best_file, best_size = None, 0
    for root, _, files in os.walk(folder):
        for f in files:
            if f.lower().endswith((".mp4", ".mkv")):
                fp = os.path.join(root, f)
                sz = os.path.getsize(fp)
                if sz > best_size:
                    best_size = sz
                    best_file = fp
    return best_file

def download_via_direct_fallback(movie_title, work_dir):
    """Scrapes direct download links from Indian/Bollywood indexes if torrent fails"""
    scraper = cloudscraper.create_scraper()
    output_file = os.path.join(work_dir, "fallback_movie.mp4")
    try:
        search_url = f"https://vegamovies.ist/?s={movie_title.replace(' ', '+')}"
        res = scraper.get(search_url, timeout=15)
        if res.status_code == 200:
            soup = BeautifulSoup(res.text, 'html.parser')
            post = soup.select_section('div.title a, h2.title a, .poster-container a') if hasattr(soup, 'select_section') else soup.select('h2 a, .title a')
            if post:
                post_url = post[0]['href']
                p_res = scraper.get(post_url, timeout=15)
                p_soup = BeautifulSoup(p_res.text, 'html.parser')
                for a in p_soup.select('a.download-button, a[href*="pixeldrain"], a[href*="hubcloud"]'):
                    dl_link = a['href']
                    if dl_link:
                        subprocess.run(["yt-dlp", "--no-part", "-o", output_file, dl_link], timeout=250)
                        if verify_video_file(output_file):
                            return output_file
    except Exception:
        pass
    return None

def download_movie_hybrid(imdb_id, movie_title, work_dir):
    """Step 1: Try Fast Torrent. Step 2: Fallback to Direct DDL if torrent fails."""
    if os.path.exists(work_dir):
        shutil.rmtree(work_dir, ignore_errors=True)
    os.makedirs(work_dir, exist_ok=True)

    # 1. Try Torrents with fast 20s timeout
    for mag in fetch_magnets_from_torrentio(imdb_id):
        cmd = ["aria2c", "--seed-time=0", "--bt-tracker=" + TRACKERS, "--bt-stop-timeout=20", "--max-tries=2", "-d", work_dir, mag]
        try:
            subprocess.run(cmd, timeout=100)
            vf = find_largest_video(work_dir)
            if vf and verify_video_file(vf):
                return vf
        except Exception:
            pass
        shutil.rmtree(work_dir, ignore_errors=True)
        os.makedirs(work_dir, exist_ok=True)

    # 2. Fallback to Direct Web/Cloud Link if torrent had no seeders
    print(f"Torrent failed or no seeders for {movie_title}. Switching to Direct Cloud Fallback...")
    direct_file = download_via_direct_fallback(movie_title, work_dir)
    if direct_file and verify_video_file(direct_file):
        return direct_file

    return None

def upload_to_archive_and_sync(meta, video_path):
    tmdb_id = str(meta["id"]) if "id" in meta else str(meta["tmdb_id"])
    ext = os.path.splitext(video_path)[1].lower()
    cf = f"sijj_movie_{tmdb_id}{ext}"
    ident = f"sijjhub-media-{tmdb_id}-{int(time.time())}"
    tp = os.path.join(os.path.dirname(video_path), cf)
    os.rename(video_path, tp)

    r = ia.upload(ident, files=[tp], metadata={"title": f"SijjHub {tmdb_id}", "mediatype": "movies"}, access_key=IA_ACCESS, secret_key=IA_SECRET)
    if r and r[0].status_code == 200:
        url = f"https://archive.org/download/{ident}/{cf}"
        meta.update({"stream_url": url, "terabox_url": url, "category": "Trending Hollywood (Hindi Dubbed)" if meta["hindi_dubbed"] else "Popular Updates"})
        requests.put(f"{FIREBASE_URL}/movies/{tmdb_id}.json", data=json.dumps(meta), timeout=15)
        return True
    return False

def run_bot():
    completed = 0
    for page in range(1, 15):
        if completed >= MAX_MOVIES_PER_RUN: break
        lang = "&with_original_language=hi" if (BOT_ID % 2 == 1) else ""
        url = f"https://api.themoviedb.org/3/discover/movie?api_key={TMDB_API_KEY}&sort_by=popularity.desc&primary_release_date.gte={YEAR_START}-01-01&primary_release_date.lte={YEAR_END}-12-31&page={page}{lang}"
        try:
            for m in requests.get(url, timeout=15).json().get("results", []):
                if completed >= MAX_MOVIES_PER_RUN: break
                tmdb_id = str(m.get("id"))
                if is_already_in_firebase(tmdb_id): continue
                
                title = m.get("title", "Movie")
                wd = f"/tmp/w_{BOT_ID}_{tmdb_id}"
                imdb, hindi = get_imdb_and_hindi_status(tmdb_id)
                
                vp = download_movie_hybrid(imdb, title, wd)
                if vp:
                    meta = {"tmdb_id": tmdb_id, "id": tmdb_id, "title": title, "overview": m.get("overview",""), "release_date": m.get("release_date",""), "poster": f"https://image.tmdb.org/t/p/w500{m.get('poster_path')}" if m.get("poster_path") else "", "hindi_dubbed": hindi or (m.get("original_language")=="hi")}
                    if upload_to_archive_and_sync(meta, vp): completed += 1
                shutil.rmtree(wd, ignore_errors=True)
        except Exception:
            pass

if __name__ == "__main__":
    run_bot()