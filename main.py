import re
import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

app = FastAPI(title="SijjMoviesHub Proxy Streaming Bridge", version="2.0")

# 1. CORS SETUP: Allow all origins and methods for mobile application communication
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/api/get-movie")
async def get_movie(url: str = Query(..., description="Raw magnet link from Firebase Realtime Database")):
    """
    Endpoint that accepts a magnet link, validates it, extracts infohash as fallback,
    and proxies the video stream seamlessly via webtor.io without native C++ compilation.
    """
    # 2. Validate URL format
    if not url or not url.startswith("magnet:"):
        raise HTTPException(
            status_code=400,
            detail="Invalid or missing magnet link. URL must start with 'magnet:'"
        )

    # 3. Extract infohash using regex (fallback logging/verification)
    infohash_match = re.search(r"xt=urn:btih:([a-zA-Z0-9]+)", url, re.IGNORECASE)
    infohash = infohash_match.group(1) if infohash_match else "unknown"

    # Construct public online stream extractor cluster URL
    proxy_target_url = f"https://webtor.io/{url}"

    try:
        # 4. Use httpx AsyncClient to open an asynchronous streaming network pipe
        client = httpx.AsyncClient(timeout=None, follow_redirects=True)
        
        # We request the stream from the extractor cluster
        req = client.build_request("GET", proxy_target_url)
        r = await client.send(req, stream=True)

        if r.status_code >= 400:
            await client.aclose()
            raise HTTPException(
                status_code=r.status_code,
                detail=f"Remote proxy cluster returned error status: {r.status_code}"
            )

        # 5. Create async generator function to stream remote proxy video packets byte-by-byte
        async def proxy_generator():
            try:
                async for chunk in r.aiter_bytes(chunk_size=65536):
                    if chunk:
                        yield chunk
            except Exception as stream_err:
                print(f"Proxy chunk streaming error: {stream_err}")
            finally:
                await r.aclose()
                await client.aclose()

        # 6. Control headers for mobile expo-video player seeking support
        headers = {
            "Accept-Ranges": "bytes",
            "Content-Disposition": "inline; filename=moviebox_stream.mp4",
        }

        return StreamingResponse(
            proxy_generator(),
            media_type="video/mp4",
            headers=headers
        )

    except Exception as e:
        print(f"Proxy bridge execution exception for infohash {infohash}: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to proxy stream from extractor network: {str(e)}"
        )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)