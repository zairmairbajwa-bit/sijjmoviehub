import os
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
import torrentstream

app = FastAPI(title="SijjMoviesHub Streaming Bridge", version="1.0")

# 1. CORS SETUP: Allow all origins and methods for mobile application communication
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/api/get-movie")
async def get_movie(url: str = Query(..., description="Raw magnet link from Firebase")):
    """
    Endpoint that accepts a magnet link, initializes torrentstream,
    finds the largest video file, and streams it back chunk-by-chunk.
    """
    # 2. Validate URL format
    if not url or not url.startswith("magnet:"):
        raise HTTPException(
            status_code=400,
            detail="Invalid or missing magnet link. URL must start with 'magnet:'"
        )

    try:
        # 3. Initialize and load torrent asynchronously
        ts = torrentstream.Torrent(url)
        await ts.load()

        if not ts.files:
            raise HTTPException(
                status_code=404,
                detail="No media files found inside this torrent bundle."
            )

        # 4. Automatically select the largest file (main movie file)
        video_file = max(ts.files, key=lambda f: f.length)
        file_name = os.path.basename(video_file.name) or "movie.mp4"

        # 5. Define streaming generator to serve data byte-by-byte
        async def file_streamer():
            try:
                async for chunk in video_file.stream():
                    yield chunk
            except Exception as stream_err:
                print(f"Streaming chunk error: {stream_err}")

        # 6. Return StreamingResponse with required media headers for mobile video seeking
        headers = {
            "Accept-Ranges": "bytes",
            "Content-Disposition": f"inline; filename={file_name}",
        }

        return StreamingResponse(
            file_streamer(),
            media_type="video/mp4",
            headers=headers
        )

    except Exception as e:
        # 7. Graceful error handling for zero seeds, buffering timeouts, or invalid torrents
        print(f"Torrent stream engine exception: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to resolve or buffer torrent stream: {str(e)}"
        )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)