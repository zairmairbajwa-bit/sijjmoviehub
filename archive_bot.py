import os
import sys
import time
import json
import shutil
import requests
import subprocess
import internetarchive as ia

TMDB_API_KEY = "7b6a89d3dc55b3a81aa892a88c0da6b9"
FIREBASE_URL = "https://sijjmoviehub-default-rtdb.firebaseio.com"

BOT_ID = int(os.getenv("BOT_ID", "1"))
YEAR_START = int(os.getenv("YEAR_START", "2025"))
YEAR_END = int(os.getenv("YEAR_END", "2026"))
IA_ACCESS = os.getenv("IA_ACCESS", "").strip()
IA_SECRET = os.getenv("IA_SECRET", "").strip()
MAX_MOVIES_PER_RUN = 12

def is_already_in_firebase(tmdb_id):
    """Checks if the movie is already saved in Firebase to prevent duplicates."""
    try:
        res = requests.get(f"{FIREBASE_URL}/movies/{tmdb_id}.json", timeout=10)
        if res.status_code == 200 and res.json():
            data = res.json()
            if "archive.org/download/" in data.get("stream_url", ""):
                return True
    except Exception:
        pass
    return False

def get_hindi_status(tmdb_id):
    """Checks if Hindi translation is available for the movie."""
    try:
        trans = requests.get(f"https://api.themoviedb.org/3/movie/{tmdb_id}/translations?api_key={TMDB_API_KEY}", timeout=10).json()
        return any(t.get("iso_639_1") == "hi" for t in trans.get("translations", []))
    except Exception:
        return False

def verify_video_file(filepath):
    """Strict Verification: Rejects samples, text files, and ensures size > 300MB and duration > 40 mins."""
    if not os.path.exists(filepath): 
        return False
    
    size_mb = os.path.getsize(filepath) / (1024 * 1024)
    # Reject anything smaller than 300MB or larger than 5GB
    if size_mb < 300 or size_mb > 5000:
        print(f"Rejected invalid file size: {size_mb:.1f} MB")
        return False
        
    try:
        cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", filepath]
        output = subprocess.check_output(cmd, stderr=subprocess.STDOUT).decode().strip()
        duration_mins = float(output) / 60.0
        print(f"Verified valid movie: {size_mb:.1f} MB | Duration: {duration_mins:.1f} mins")
        return duration_mins >= 40.0
    except Exception as e:
        print(f"FFprobe check failed: {e}")
        return False

def download_movie_direct(tmdb_id, work_dir):
    """Downloads movie using high-speed Direct Cloud / HLS extractors without any torrent/seeders delay."""
    if os.path.exists(work_dir):
        shutil.rmtree(work_dir, ignore_errors=True)
    os.makedirs(work_dir, exist_ok=True)

    output_file = os.path.join(work_dir, f"movie_{tmdb_id}.mp4")
    
    # High-speed streaming embed sources for direct ripping
    direct_sources = [
        f"https://autoembed.cc/embed/movie/{tmdb_id}",
        f"https://vidlink.pro/movie/{tmdb_id}"
    ]

    for url in direct_sources:
        print(f"Trying Direct Cloud Extractor on: {url}")
        cmd = [
            "yt-dlp", "--no-part", "--concurrent-fragments", "16",
            "-f", "bestvideo[height<=1080]+bestaudio/best[height<=1080]/best",
            "--merge-output-format", "mp4",
            "-o", output_file, url
        ]
        try:
            subprocess.run(cmd, timeout=300)
            if verify_video_file(output_file):
                return output_file
        except Exception as e:
            print(f"Extractor error: {e}")
            
    return None

def upload_to_archive_and_sync(meta, video_path):
    """Uploads verified movie file to Archive.org and syncs permanent link and poster to Firebase."""
    tmdb_id = str(meta["id"])
    ext = os.path.splitext(video_path)[1].lower()
    clean_filename = f"sijj_movie_{tmdb_id}{ext}"
    identifier = f"sijjhub-media-{tmdb_id}-{int(time.time())}"
    
    target_path = os.path.join(os.path.dirname(video_path), clean_filename)
    os.rename(video_path, target_path)

    print(f"Uploading {clean_filename} to Archive.org...")
    metadata = {
        "title": f"SijjHub Media {tmdb_id}",
        "mediatype": "movies",
        "collection": "opensource_movies"
    }

    r = ia.upload(
        identifier,
        files=[target_path],
        metadata=metadata,
        access_key=IA_ACCESS,
        secret_key=IA_SECRET,
        retries=3,
        retries_sleep=10
    )

    if r and r[0].status_code == 200:
        permanent_url = f"https://archive.org/download/{identifier}/{clean_filename}"
        print(f"SUCCESS! Permanent Link: {permanent_url}")

        meta.update({
            "stream_url": permanent_url,
            "terabox_url": permanent_url,
            "category": "Trending Hollywood (Hindi Dubbed)" if meta["hindi_dubbed"] else "Popular Updates"
        })
        requests.put(f"{FIREBASE_URL}/movies/{tmdb_id}.json", data=json.dumps(meta), timeout=15)
        return True
    return False

def run_bot():
    completed = 0
    for page in range(1, 15):
        if completed >= MAX_MOVIES_PER_RUN: 
            break
            
        lang_filter = "&with_original_language=hi" if (BOT_ID % 2 == 1) else ""
        url = (
            f"https://api.themoviedb.org/3/discover/movie?api_key={TMDB_API_KEY}"
            f"&sort_by=popularity.desc&primary_release_date.gte={YEAR_START}-01-01"
            f"&primary_release_date.lte={YEAR_END}-12-31&page={page}{lang_filter}"
        )
        
        try:
            results = requests.get(url, timeout=15).json().get("results", [])
            for m in results:
                if completed >= MAX_MOVIES_PER_RUN: 
                    break
                    
                tmdb_id = str(m.get("id"))
                
                # Check 1: Skip if already in Firebase (No duplicate downloads)
                if is_already_in_firebase(tmdb_id):
                    print(f"Skipping {tmdb_id} - Already exists in Firebase database.")
                    continue

                work_dir = f"/tmp/work_{BOT_ID}_{tmdb_id}"
                has_hindi = get_hindi_status(tmdb_id)
                
                # Download using high-speed direct cloud links (No torrents, no waiting for seeders)
                video_path = download_movie_direct(tmdb_id, work_dir)
                
                if video_path:
                    meta = {
                        "tmdb_id": tmdb_id,
                        "title": m.get("title", "Untitled"),
                        "overview": m.get("overview", ""),
                        "release_date": m.get("release_date", ""),
                        "poster": f"https://image.tmdb.org/t/p/w500{m.get('poster_path')}" if m.get("poster_path") else "",
                        "hindi_dubbed": has_hindi or (m.get("original_language") == "hi")
                    }
                    if upload_to_archive_and_sync(meta, video_path):
                        completed += 1
                        
                shutil.rmtree(work_dir, ignore_errors=True)
        except Exception as e:
            print(f"Discovery error: {e}")

    print(f"=== Bot #{BOT_ID} finished run. Total uploaded: {completed} ===")

if __name__ == "__main__":
    run_bot()