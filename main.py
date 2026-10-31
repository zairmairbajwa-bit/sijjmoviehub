import os
import re
import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

app = FastAPI(title="SijjMoviesHub Zero-Database-Link Engine", version="4.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/api/get-fresh-stream")
async def get_fresh_stream(tmdb_id: str = Query(..., description="TMDB Movie ID")):
    """
    Sequentially queries AutoEmbed, VidLink, and Cinesrc proxies on-the-fly 
    to extract unexpired fresh media stream URLs (.mp4 or .m3u8).
    """
    sources = [
        f"https://autoembed.cc/embed/movie/{tmdb_id}",
        f"https://vidlink.pro/movie/{tmdb_id}",
        f"https://cinesrc.xyz/embed?id={tmdb_id}"
    ]

    async with httpx.AsyncClient(timeout=12, follow_redirects=True) as client:
        for source_url in sources:
            try:
                headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "Referer": "https://autoembed.cc/"
                }
                res = await client.get(source_url, headers=headers)
                if res.status_code == 200:
                    html_content = res.text
                    # Trace underlying media stream container (.mp4 or adaptive .m3u8)
                    match = re.search(r'https?://[^\s<>"]+?\.(?:m3u8|mp4)', html_content)
                    if match:
                        return {
                            "success": True,
                            "source_provider": source_url,
                            "stream_url": match.group(0)
                        }
                    # Fallback to direct embed source if regex scan misses raw container
                    return {
                        "success": True,
                        "source_provider": source_url,
                        "stream_url": source_url
                    }
            except Exception:
                continue

    raise HTTPException(
        status_code=404,
        detail="All multi-source streaming index nodes failed to resolve media container."
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)