import os
import sys
import time
import json
import shutil
import re
import requests
import asyncio
import internetarchive as ia
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.functions.messages import SearchGlobalRequest
from telethon.tl.types import InputMessagesFilterVideo

# === APKI API KEYS ===
TMDB_API_KEY = "7b6a89d3dc55b3a81aa892a88c0da6b9"
FIREBASE_URL = "https://sijjmoviehub-default-rtdb.firebaseio.com"

# === TELEGRAM KEYS (GitHub Secrets) ===
TG_API_ID = os.getenv("TG_API_ID")
TG_API_HASH = os.getenv("TG_API_HASH")
TG_SESSION = os.getenv("TG_SESSION")

# === BOT SETTINGS ===
BOT_ID = int(os.getenv("BOT_ID", "1"))
YEAR_START = int(os.getenv("YEAR_START", "2025"))
YEAR_END = int(os.getenv("YEAR_END", "2026"))
IA_ACCESS = os.getenv("IA_ACCESS", "").strip()
IA_SECRET = os.getenv("IA_SECRET", "").strip()

MAX_MOVIES_PER_RUN = 4  # Ek waqt mein 1 bot max 4 movies karega (4x8=32 movies har run mein)

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
    # Archive upload command
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
            "category": "Trending Hollywood (Hindi Dubbed)" if meta["hindi_dubbed"] else "Popular Updates"
        })
        # Firebase mein save
        requests.put(f"{FIREBASE_URL}/movies/{tmdb_id}.json", data=json.dumps(meta), timeout=15)
        return True
    return False

async def fetch_movie_from_telegram(client, movie_title, work_dir):
    """Telegram par movie search karke HD file download karega"""
    os.makedirs(work_dir, exist_ok=True)
    search_query = f"{movie_title} hindi"
    
    print(f"Searching Telegram for: {search_query}")
    try:
        result = await client(SearchGlobalRequest(
            q=search_query,
            filter=InputMessagesFilterVideo(),
            min_date=None,
            max_date=None,
            offset_rate=0,
            offset_peer='Empty',
            offset_id=0,
            limit=10
        ))
        
        for msg in result.messages:
            # Sirf 350MB se badi HD files uthayega
            if msg.document and msg.file.size > 350 * 1024 * 1024:
                print(f"Match Found! Size: {msg.file.size / (1024*1024):.2f} MB. Downloading...")
                file_path = await client.download_media(msg, file=work_dir)
                if file_path:
                    print(f"Download complete: {file_path}")
                    return file_path
    except Exception as e:
        print(f"Telegram search error: {e}")
        
    return None

async def main():
    if not TG_API_ID or not TG_API_HASH or not TG_SESSION:
        print("ERROR: Telegram API Keys ya Session missing hain!")
        return

    print(f"Starting Bot ID: {BOT_ID}")
    
    # Desktop spoofing ke sath Telegram client taake connection safe rahe
    client = TelegramClient(
        StringSession(TG_SESSION), 
        int(TG_API_ID), 
        TG_API_HASH,
        device_model="Desktop", 
        system_version="Windows 10", 
        app_version="4.8.1"
    )
    await client.connect()
    
    if not await client.is_user_authorized():
        print("Telegram Session invalid hai!")
        return
    print("Telegram Connected Successfully!")
        
    completed = 0
    start_time = time.time()
    
    # Bot 1-4 Hollywood Dubbed ke liye, Bot 5-8 Bollywood Original ke liye
    lang = "&with_original_language=hi" if (BOT_ID > 4) else ""
    
    # Har bot apne number se page start karega (1, 2, 3...) aur 8 ka jump lega (9, 10, 11...)
    for page in range(BOT_ID, 50, 8):
        if completed >= MAX_MOVIES_PER_RUN: break
        if (time.time() - start_time) > 3300: # 55 min timeout
            print("Time limit reached. Stopping gracefully.")
            break 

        url = f"https://api.themoviedb.org/3/discover/movie?api_key={TMDB_API_KEY}&sort_by=popularity.desc&primary_release_date.gte={YEAR_START}-01-01&primary_release_date.lte={YEAR_END}-12-31&page={page}{lang}"
        
        try:
            res = requests.get(url, timeout=15).json()
            for m in res.get("results", []):
                if completed >= MAX_MOVIES_PER_RUN: break
                
                tmdb_id = str(m.get("id"))
                if is_already_in_firebase(tmdb_id): continue
                
                title = m.get("title", "Untitled")
                imdb, hindi = get_imdb_and_hindi_status(tmdb_id)
                wd = f"/tmp/w_{BOT_ID}_{tmdb_id}"
                
                # Fetch -> Upload -> Sync
                vp = await fetch_movie_from_telegram(client, title, wd)
                
                if vp:
                    meta = {
                        "tmdb_id": tmdb_id, "id": tmdb_id, "title": title, 
                        "overview": m.get("overview", ""), "release_date": m.get("release_date", ""), 
                        "poster": f"https://image.tmdb.org/t/p/w500{m.get('poster_path')}" if m.get('poster_path') else "", 
                        "hindi_dubbed": hindi or (m.get("original_language") == "hi")
                    }
                    if upload_to_archive_and_sync(meta, vp):
                        completed += 1
                        print(f"Successfully processed and synced: {title}")
                        
                # Har movie ke baad kachra saaf karega
                shutil.rmtree(wd, ignore_errors=True)
        except Exception as e:
            print(f"Run exception encountered: {e}")

    await client.disconnect()
    print("Bot run completed.")

if __name__ == "__main__":
    asyncio.run(main())