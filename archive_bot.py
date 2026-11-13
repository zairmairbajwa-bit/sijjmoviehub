import os
import time
import json
import re
import urllib.parse
import requests
import subprocess
import internetarchive as ia
import shutil

TMDB_API_KEY = os.getenv("TMDB_API_KEY", "").strip() or "7b6a89d3dc55b3a81aa892a88c0da6b9"
FIREBASE_URL = os.getenv("FIREBASE_URL", "").strip() or "https://sijjmoviehub-default-rtdb.firebaseio.com"
BASE_DOMAIN = "https://filmy-hd.online"

BOT_ID = int(os.getenv("BOT_ID", "1") or "1")
actual_bot_account_id = ((BOT_ID - 1) % 4) + 1
IA_ACCESS = os.getenv(f"IA_ACCESS_{actual_bot_account_id}", "").strip()
IA_SECRET = os.getenv(f"IA_SECRET_{actual_bot_account_id}", "").strip()

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Referer": BASE_DOMAIN
})

BOT_TARGETS = {
    1: "bollywood-hindi-movies/",
    2: "hollywood-hindi-movies/",
    3: "bollywood-hindi-movies/", 
    4: "imdb-top-movies/",
    5: "punjabi-movies/",
    6: "south-hindi-dubbed-movie/",
    7: "web-series/",
    8: "animation-movies/"
}

def clean_filename(name):
    cleaned = re.sub(r'[^a-zA-Z0-9_-]', '_', name)
    return re.sub(r'_+', '_', cleaned).strip('_')

def is_valid_movie_url(url):
    low = url.lower()
    if ".html" in low and not any(x in low for x in ["/page/", "/category/", "dmca", "contact", "privacy"]):
        return True
    return False

def fetch_tmdb_metadata(raw_title):
    clean_query = re.sub(r'(?i)(Dual Audio|Hindi \+ English|Animated Movie|Animation Movie|BluRay|HD|ESub|Full Movie|Download|Web-DL).*', '', raw_title)
    year_match = re.search(r'\((\d{4})\)|\[(\d{4})\]', clean_query)
    release_year = year_match.group(1) or year_match.group(2) if year_match else "2026"
    
    clean_query = re.sub(r'\(\d{4}\)|\[\d{4}\]', '', clean_query)
    clean_query = re.sub(r'\(.*?\)|\[.*?\]', '', clean_query).strip()
    
    search_url = f"https://api.themoviedb.org/3/search/movie?api_key={TMDB_API_KEY}&query={urllib.parse.quote(clean_query)}"
    try:
        resp = requests.get(search_url, timeout=10)
        if resp.status_code == 200:
            results = resp.json().get("results", [])
            if results:
                m = results[0]
                return {
                    "title": m.get("title", clean_query),
                    "overview": m.get("overview", raw_title),
                    "release_date": m.get("release_date", release_year)[:4],
                    "poster": f"https://image.tmdb.org/t/p/w500{m.get('poster_path')}" if m.get('poster_path') else "",
                    "tmdb_matched": True
                }
    except:
        pass
        
    fallback_title = clean_query.replace('-', ' ').replace('_', ' ').strip()
    if not fallback_title:
        fallback_title = "Unknown_Movie"
    return {
        "title": fallback_title, "overview": raw_title,
        "release_date": release_year, "poster": "", "tmdb_matched": False
    }

def upload_and_sync(meta, unique_key, ident, res_label, f_path, bot_id):
    ext = ".mp4"
    release_year = meta.get("release_date", "2026")
    safe_title = clean_filename(meta['title'])
    file_name = f"{safe_title}_{release_year}_{res_label}_{unique_key}{ext}"
    tp = os.path.join(os.path.dirname(f_path), file_name)
    
    if f_path != tp: 
        shutil.move(f_path, tp)
    
    attempt = 0
    while True:
        attempt += 1
        print(f"🚀 [BOT {bot_id}] UPLOADING TO ARCHIVE (Attempt {attempt}): {meta['title']} [{res_label}]...", flush=True)
        try:
            r = ia.upload(
                ident, files=[tp], 
                metadata={"title": f"{meta['title']} ({release_year})", "mediatype": "movies"}, 
                access_key=IA_ACCESS, secret_key=IA_SECRET
            )
            
            if r and r[0].status_code == 200:
                print(f"✅ [BOT {bot_id}] {res_label} UPLOAD SUCCESS! Syncing to Firebase...", flush=True)
                archive_link = f"https://archive.org/download/{ident}/{file_name}"
                db_key = f"url_{res_label}"
                
                meta[db_key] = archive_link
                meta["stream_url"] = archive_link 
                
                requests.patch(f"{FIREBASE_URL}/movies/{unique_key}.json", data=json.dumps({db_key: archive_link, "stream_url": archive_link}), timeout=15)
                requests.patch(f"{FIREBASE_URL}/movies/{unique_key}.json", data=json.dumps(meta), timeout=15)
                
                try: os.remove(tp)
                except: pass
                return True
        except Exception as e:
            print(f"⚠️ [BOT {bot_id}] Upload error: {e}. Waiting 15 seconds before retry...", flush=True)
            time.sleep(15)

def get_resolution_links(movie_page_url):
    try:
        resp = session.get(movie_page_url, timeout=15)
        resolutions = {}
        
        for match in re.finditer(r'<a\s+[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', resp.text, re.IGNORECASE | re.DOTALL):
            href = match.group(1)
            text = re.sub(r'<[^>]+>', '', match.group(2)).lower().strip()
            link = urllib.parse.urljoin(BASE_DOMAIN, href)
            
            low_link = link.lower()
            if any(k in low_link for k in ["whatsapp", "telegram", "facebook", "category", "javascript", "dmca"]):
                continue
                
            res_label = None
            if "720p" in text or "720" in low_link:
                res_label = "720p"
            elif "480p" in text or "300mb" in text or "480" in low_link:
                res_label = "480p"
            elif "1080p" in text or "1080" in low_link:
                continue 
                
            if res_label and res_label not in resolutions:
                resolutions[res_label] = link
                
        return resolutions
    except:
        return {}

# 💡 THE FIX: Smart Resolver for l.php links!
def resolve_actual_download_link(url):
    try:
        print(f"🔍 [BOT {BOT_ID}] Resolving l.php link: {url}", flush=True)
        # Follow HTTP redirects aggressively
        resp = session.get(url, timeout=20, allow_redirects=True)
        current_url = resp.url
        
        if "l.php" not in current_url and current_url != url:
            print(f"🎯 Redirected to: {current_url[:60]}...", flush=True)
            return current_url
            
        # Check for Meta Refresh Redirect in HTML
        meta_match = re.search(r'(?i)<meta\s+http-equiv=["\']refresh["\']\s+content=["\']\d+;\s*url=([^"\']+)["\']', resp.text)
        if meta_match:
            new_link = urllib.parse.urljoin(current_url, meta_match.group(1))
            print(f"🎯 Meta Refresh Found: {new_link[:60]}...", flush=True)
            return new_link

        # Check for Javascript Redirect
        js_match = re.search(r'(?i)window\.location(?:\.href)?\s*=\s*["\']([^"\']+)["\']', resp.text)
        if js_match:
            new_link = urllib.parse.urljoin(current_url, js_match.group(1))
            print(f"🎯 JS Redirect Found: {new_link[:60]}...", flush=True)
            return new_link

        # Look for the final external download button link
        for match in re.finditer(r'<a\s+[^>]*href=["\']([^"\']+)["\'][^>]*>', resp.text, re.IGNORECASE):
            href = match.group(1)
            if href.startswith("http") and "filmy-hd.online" not in href.lower() and not any(skip in href.lower() for skip in ["whatsapp", "telegram", "facebook", "twitter"]):
                print(f"🎯 External Button Link Found: {href[:60]}...", flush=True)
                return href
                
        return current_url
    except Exception as e:
        print(f"⚠️ Error resolving link: {e}", flush=True)
        return url

def download_with_aria2(url, work_dir):
    cmd = [
        "aria2c", "--dir=" + work_dir, "--seed-time=0", 
        "-x", "4", "-s", "4", 
        "-c", "--max-tries=3", "--retry-wait=2", "--connect-timeout=15",
        "--content-disposition-default-utf8=true",
        "--header=User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        url
    ]
    try: 
        subprocess.run(cmd, check=True, timeout=7200, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except: 
        pass 
            
    largest_file = None
    max_size = -1
    for root, dirs, files in os.walk(work_dir):
        for file in files:
            if file.endswith(".aria2"): continue
            f_path = os.path.join(root, file)
            try:
                size = os.path.getsize(f_path)
                if size > max_size:
                    max_size = size
                    largest_file = f_path
            except: pass
            
    return largest_file

def process_single_content(m_url):
    try:
        m_resp = session.get(m_url, timeout=20)
    except: 
        return
    
    title_match = re.search(r'<title>(.*?)</title>', m_resp.text, re.IGNORECASE)
    raw_title = title_match.group(1) if title_match else "Movie"
    unique_key = abs(hash(m_url)) % (10 ** 10)
    
    try:
        res_check = requests.get(f"{FIREBASE_URL}/movies/{unique_key}.json", timeout=5)
        if res_check.status_code == 200 and res_check.json():
            data = res_check.json()
            if data.get("url_480p") or data.get("url_720p") or data.get("stream_url"):
                print(f"⏭️ [BOT {BOT_ID}] ALREADY IN DB SKIPPED: '{raw_title[:30]}'", flush=True)
                return True
    except: 
        pass

    tmdb_meta = fetch_tmdb_metadata(raw_title)
    print(f"🎬 [BOT {BOT_ID}] Processing: '{tmdb_meta['title']}' (TMDB Matched: {tmdb_meta['tmdb_matched']})", flush=True)

    resolution_links = get_resolution_links(m_url)
    if not resolution_links:
        print(f"⚠️ [BOT {BOT_ID}] No resolutions found for: '{tmdb_meta['title']}'", flush=True)
        return False

    wd = f"/tmp/sijj_{BOT_ID}_{unique_key}"
    os.makedirs(wd, exist_ok=True)
    ident = f"sijjhub-media-{unique_key}-{int(time.time())}"
    
    meta = {
        "tmdb_id": str(unique_key), "id": str(unique_key), "title": tmdb_meta['title'], 
        "overview": tmdb_meta['overview'], "release_date": tmdb_meta['release_date'], 
        "poster": tmdb_meta['poster'], "hindi_dubbed": True, "category": BOT_TARGETS.get(BOT_ID, "movies"),
        "is_series": False
    }

    # 💡 STRICT SEQUENTIAL & ISOLATED RESOLUTION DOWNLOAD
    for res_label in ["480p", "720p"]:
        if res_label not in resolution_links:
            continue
            
        intermediate_link = resolution_links[res_label]
        actual_download_link = resolve_actual_download_link(intermediate_link)
        
        print(f"📥 [BOT {BOT_ID}] DOWNLOADING {res_label}: {tmdb_meta['title']}...", flush=True)
        
        f_path = download_with_aria2(actual_download_link, wd)
        if f_path:
            file_size_mb = os.path.getsize(f_path) / (1024 * 1024)
            if file_size_mb > 30:
                print(f"🟢 [BOT {BOT_ID}] Downloaded successfully ({file_size_mb:.2f}MB). Uploading to Archive...", flush=True)
                upload_success = upload_and_sync(meta, str(unique_key), ident, res_label, f_path, BOT_ID)
                if upload_success:
                    print(f"🎉 [BOT {BOT_ID}] Completed & Synced: {tmdb_meta['title']} [{res_label}]", flush=True)
            else:
                print(f"❌ [BOT {BOT_ID}] File too small ({file_size_mb:.2f}MB). Download blocked or fake file! Deleted.", flush=True)
                try: os.remove(f_path)
                except: pass
        else:
            print(f"❌ [BOT {BOT_ID}] aria2c failed to download any file for {res_label}.", flush=True)
            
        time.sleep(3)

    shutil.rmtree(wd, ignore_errors=True)
    return True

def run_bot():
    category_slug = BOT_TARGETS.get(BOT_ID, "bollywood-hindi-movies/")
    base_cat_url = f"{BASE_DOMAIN}/{category_slug}"
    
    print(f"🔥 Starting Bot ID: {BOT_ID} - Target Category: {category_slug}", flush=True)
    start_time = time.time()
    
    # Strictly 1 by 1 page scanning without limits
    p_num = 1
    while True:
        if (time.time() - start_time) > 25000:
            break
            
        p_url = base_cat_url if p_num == 1 else f"{base_cat_url}page/{p_num}/"
        print(f"📄 [BOT {BOT_ID}] Scanning Page {p_num}: {p_url}", flush=True)
        
        try:
            resp = session.get(p_url, timeout=15)
            if resp.status_code != 200:
                break
                
            page_movie_links = []
            for match in re.finditer(r'<a\s+[^>]*href=["\']([^"\']+)["\'][^>]*>', resp.text, re.IGNORECASE):
                href = match.group(1)
                link = urllib.parse.urljoin(BASE_DOMAIN, href)
                if is_valid_movie_url(link) and link not in page_movie_links:
                    page_movie_links.append(link)
            
            if not page_movie_links:
                break
                
            print(f"🎯 [BOT {BOT_ID}] Found {len(page_movie_links)} movies on Page {p_num}. Processing sequentially 1 by 1...", flush=True)
            
            for m_url in page_movie_links:
                process_single_content(m_url)
                
        except Exception as e:
            print(f"⚠️ [BOT {BOT_ID}] Error scanning page {p_num}: {e}", flush=True)
            break
            
        p_num += 1

    print(f"🏁 [BOT {BOT_ID}] BOT RUN COMPLETE!", flush=True)

if __name__ == "__main__":
    run_bot()
