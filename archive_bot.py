import os, time, json, re, urllib.parse, requests, subprocess, shutil, hashlib, random
import internetarchive as ia

TMDB_API_KEY = os.getenv("TMDB_API_KEY", "").strip()
FIREBASE_URL = os.getenv("FIREBASE_URL", "").strip()
FIREBASE_SECRET = os.getenv("FIREBASE_SECRET", "").strip()
BASE_DOMAIN = "https://filmy-hd.online"

BOT_ID = int(os.getenv("BOT_ID", "1") or "1")

# 7 Accounts Formula
actual_bot_account_id = ((BOT_ID - 1) % 7) + 1
IA_ACCESS = os.getenv(f"IA_ACCESS_{actual_bot_account_id}", "").strip()
IA_SECRET = os.getenv(f"IA_SECRET_{actual_bot_account_id}", "").strip()

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "*/*",
    "Referer": BASE_DOMAIN
})

BOT_TARGETS = {
    1: "bollywood-hindi-movies/",
    2: "hollywood-hindi-movies/",
    3: "",
    4: "imdb-top-movies/",
    5: "punjabi-movies/",
    6: "south-hindi-dubbed-movie/",
    7: "web-series/",
    8: "animation-movies/"
}

def clean_filename(name):
    return re.sub(r'_+', '_', re.sub(r'[^a-zA-Z0-9_-]', '_', name)).strip('_')

def is_valid_movie_url(url):
    return ".html" in url.lower() and not any(x in url.lower() for x in ["/page/", "/category/", "dmca", "contact", "privacy"])

def fetch_tmdb_metadata(raw_title):
    clean_query = re.sub(r'(?i)(Dual Audio|Hindi \+ English|Animated Movie|Animation Movie|BluRay|HD|ESub|Full Movie|Download|Web-DL|Panjabi Movie|Punjabi Movie|South Hindi Dubbed|Web Series|Season \d+|Episode \d+).*', '', raw_title)
    year_match = re.search(r'\((\d{4})\)|\[(\d{4})\]', clean_query)
    release_year = year_match.group(1) or year_match.group(2) if year_match else "2026"
    
    clean_query = re.sub(r'\(\d{4}\)|\[\d{4}\]', '', clean_query)
    clean_query = re.sub(r'\(.*?\)|\[.*?\]', '', clean_query).replace('-', ' ').replace('_', ' ').strip()
    
    try:
        resp = requests.get(f"https://api.themoviedb.org/3/search/multi?api_key={TMDB_API_KEY}&query={urllib.parse.quote(clean_query)}", timeout=10)
        if resp.status_code == 200:
            for m in resp.json().get("results", []):
                if m.get("media_type") in ["movie", "tv"]:
                    title = m.get("title") if m.get("media_type") == "movie" else m.get("name")
                    rel_date = m.get("release_date") if m.get("media_type") == "movie" else m.get("first_air_date")
                    return {
                        "title": title or clean_query,
                        "overview": m.get("overview", raw_title),
                        "release_date": rel_date[:4] if rel_date else release_year,
                        "poster": f"https://image.tmdb.org/t/p/w500{m.get('poster_path')}" if m.get('poster_path') else "",
                        "tmdb_matched": True,
                        "is_series": m.get("media_type") == "tv"
                    }
    except: pass
    
    return {"title": clean_query or "Unknown_Movie", "overview": raw_title, "release_date": release_year, "poster": "", "tmdb_matched": False, "is_series": False}

def upload_and_sync(meta, unique_key, ident, res_label, f_path, bot_id):
    ext = ".mp4"
    file_name = f"{clean_filename(meta['title'])}_{meta.get('release_date', '2026')}_{res_label}_{unique_key}{ext}"
    tp = os.path.join(os.path.dirname(f_path), file_name)
    if f_path != tp: shutil.move(f_path, tp)
    
    for attempt in range(1, 5):
        print(f"🚀 [BOT {bot_id}] UPLOADING (Attempt {attempt}/4): {meta['title']} [{res_label}]...", flush=True)
        try:
            r = ia.upload(ident, files=[tp], metadata={"title": f"{meta['title']} ({meta.get('release_date', '2026')})", "mediatype": "movies"}, access_key=IA_ACCESS, secret_key=IA_SECRET)
            if r and r[0].status_code == 200:
                print(f"✅ [BOT {bot_id}] UPLOAD SUCCESS! Saving to Database...", flush=True)
                link = f"https://archive.org/download/{ident}/{file_name}"
                meta[f"url_{res_label}"] = link
                meta["stream_url"] = link 
                requests.patch(f"{FIREBASE_URL}/movies/{unique_key}.json?auth={FIREBASE_SECRET}", data=json.dumps({f"url_{res_label}": link, "stream_url": link}), timeout=15)
                requests.patch(f"{FIREBASE_URL}/movies/{unique_key}.json?auth={FIREBASE_SECRET}", data=json.dumps(meta), timeout=15)
                try: os.remove(tp)
                except: pass
                time.sleep(5)
                return True
        except Exception as e:
            print(f"⚠️ [BOT {bot_id}] Upload error. Retrying in 60s...", flush=True)
            time.sleep(60)
            
    print(f"❌ [BOT {bot_id}] Upload failed after 4 attempts. Skipping.", flush=True)
    try: os.remove(tp)
    except: pass
    return False

def get_resolution_links(url):
    try:
        resp = session.get(url, timeout=15)
        res = {}
        for match in re.finditer(r'<a\s+[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', resp.text, re.IGNORECASE | re.DOTALL):
            link = urllib.parse.urljoin(BASE_DOMAIN, match.group(1))
            text = re.sub(r'<[^>]+>', '', match.group(2)).lower()
            if any(k in link.lower() for k in ["whatsapp", "telegram", "facebook", "category", "javascript", "dmca"]): continue
            label = "720p" if "720" in text or "720" in link.lower() else "480p" if "480" in text or "300mb" in text or "480" in link.lower() else None
            if label and label not in res: res[label] = link
        return res
    except: return {}

def resolve_actual_download_link(url, ref):
    try:
        session.headers.update({"Referer": ref})
        return session.get(url, timeout=20, allow_redirects=True, stream=True).url
    except: return url

def download_with_aria2(url, work_dir, ref):
    # ⚡ 8 Connections aur 1M min-split size (Fast + 100% Safe)
    cmd = [
        "aria2c", "--dir=" + work_dir, "--seed-time=0", 
        "-x", "8", "-s", "8", "--min-split-size=1M", 
        "-c", "--max-tries=3", "--retry-wait=2", "--connect-timeout=15", 
        "--content-disposition-default-utf8=true", f"--header=Referer: {ref}", url
    ]
    try: subprocess.run(cmd, check=True, timeout=7200, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except: pass 
    
    max_size, largest = -1, None
    for r, d, f in os.walk(work_dir):
        for file in f:
            if not file.endswith(".aria2"):
                path = os.path.join(r, file)
                try:
                    sz = os.path.getsize(path)
                    if sz > max_size: max_size, largest = sz, path
                except: pass
    return largest

def process_single_content(m_url):
    try: m_resp = session.get(m_url, timeout=20)
    except: return
    
    raw_title = re.search(r'<title>(.*?)</title>', m_resp.text, re.IGNORECASE)
    raw_title = raw_title.group(1) if raw_title else "Movie"
    unique_key = int(hashlib.md5(m_url.encode()).hexdigest(), 16) % (10 ** 10)
    
    try:
        chk = requests.get(f"{FIREBASE_URL}/movies/{unique_key}.json", timeout=5)
        if chk.status_code == 200 and chk.json() and any(k in chk.json() for k in ["url_480p", "url_720p", "stream_url"]):
            print(f"⏭️ [BOT {BOT_ID}] SKIP: '{raw_title[:40]}' - (Pehle se Database mein mojood hai)", flush=True)
            return True
    except: pass

    meta = fetch_tmdb_metadata(raw_title)
    res_links = get_resolution_links(m_url)
    if not res_links: 
        print(f"⚠️ [BOT {BOT_ID}] SKIP: '{meta['title']}' - (Download links nahi mile)", flush=True)
        return False

    print(f"🎬 [BOT {BOT_ID}] FOUND NEW: '{meta['title']}' - Preparing...", flush=True)

    wd = f"/tmp/sijj_{BOT_ID}_{unique_key}"
    os.makedirs(wd, exist_ok=True)
    ident = f"sijjhub-media-{unique_key}-{int(time.time())}"
    
    full_meta = {"tmdb_id": str(unique_key), "id": str(unique_key), "title": meta['title'], "overview": meta['overview'], "release_date": meta['release_date'], "poster": meta['poster'], "hindi_dubbed": True, "category": BOT_TARGETS.get(BOT_ID, "front-page"), "is_series": meta['is_series']}

    for label in ["480p", "720p"]:
        if label not in res_links: continue
        print(f"📥 [BOT {BOT_ID}] DOWNLOADING: {meta['title']} [{label}] (8x Speed)...", flush=True)
        f_path = download_with_aria2(resolve_actual_download_link(res_links[label], m_url), wd, m_url)
        if f_path:
            mb_size = os.path.getsize(f_path) / (1024 * 1024)
            if mb_size > 30:
                print(f"🟢 [BOT {BOT_ID}] DOWNLOAD COMPLETE ({mb_size:.1f} MB) - Now Uploading...", flush=True)
                upload_and_sync(full_meta, str(unique_key), ident, label, f_path, BOT_ID)
            else:
                print(f"❌ [BOT {BOT_ID}] FAKE FILE: Size too small ({mb_size:.1f} MB). Deleted.", flush=True)
                try: os.remove(f_path)
                except: pass
        else:
            print(f"❌ [BOT {BOT_ID}] DOWNLOAD FAILED: {label}", flush=True)
        time.sleep(3)
    shutil.rmtree(wd, ignore_errors=True)
    return True

def run_bot():
    cat = BOT_TARGETS.get(BOT_ID, "")
    b_url = f"{BASE_DOMAIN}/{cat}" if cat else f"{BASE_DOMAIN}/"
    
    wait_time = random.randint(2, 45)
    print(f"⏳ [BOT {BOT_ID}] Starting in {wait_time} seconds to prevent block...", flush=True)
    time.sleep(wait_time)
    
    start_time, p_num = time.time(), 1
    while (time.time() - start_time) < 25000:
        p_url = b_url if p_num == 1 else f"{b_url}page/{p_num}/"
        print(f"📄 [BOT {BOT_ID}] ====== SCANNING PAGE {p_num} ======", flush=True)
        try:
            resp = session.get(p_url, timeout=15)
            if resp.status_code != 200: break
            links = []
            for m in re.finditer(r'<a\s+[^>]*href=["\']([^"\']+)["\'][^>]*>', resp.text, re.IGNORECASE):
                link = urllib.parse.urljoin(BASE_DOMAIN, m.group(1))
                if is_valid_movie_url(link) and link not in links: links.append(link)
            if not links: 
                print(f"🏁 [BOT {BOT_ID}] No more movies found. Finishing.", flush=True)
                break
            for l in links: process_single_content(l)
        except Exception as e: 
            print(f"⚠️ [BOT {BOT_ID}] Page error: {e}", flush=True)
            break
        p_num += 1

if __name__ == "__main__":
    run_bot()
