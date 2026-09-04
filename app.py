import os
import uuid
import glob
import asyncio
from pathlib import Path

from fastapi import FastAPI, Request, Header, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
import yt_dlp

app = FastAPI()

DOWNLOAD_DIR = Path("/tmp/videos")
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

SECRET = os.environ.get("DOWNLOADER_SECRET", "")


class DownloadRequest(BaseModel):
    url: str


def check_secret(authorization: str | None):
    if not SECRET:
        return

    if authorization != f"Bearer {SECRET}":
        raise HTTPException(status_code=401, detail="Unauthorized")


def get_base_url(request: Request):
    proto = request.headers.get("x-forwarded-proto", "https")
    host = request.headers.get("host")
    return f"{proto}://{host}"


def download_video(url: str, job_id: str):
    folder = DOWNLOAD_DIR / job_id
    folder.mkdir(parents=True, exist_ok=True)

    output = str(folder / "%(id)s.%(ext)s")

    options = {
        "outtmpl": output,
        "format": "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/b",
        "merge_output_format": "mp4",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "restrictfilenames": True,
    }

    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(url, download=True)

    files = list(folder.glob("*"))

    if not files:
        raise Exception("Видео не скачалось")

    video_file = max(files, key=lambda x: x.stat().st_size)

    return video_file, info


@app.get("/")
async def home():
    return {
        "ok": True,
        "service": "Video Downloader",
        "status": "running"
    }


@app.post("/download")
async def download(
    data: DownloadRequest,
    request: Request,
    authorization: str | None = Header(default=None)
):
    check_secret(authorization)

    if not data.url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="Invalid URL")

    job_id = uuid.uuid4().hex

    try:
        video_file, info = await asyncio.to_thread(
            download_video,
            data.url,
            job_id
        )

        filename = video_file.name
        base_url = get_base_url(request)
        file_url = f"{base_url}/files/{job_id}/{filename}"

        return {
            "success": True,
            "url": file_url,
            "filename": filename,
            "title": info.get("title", "Видео")
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


@app.get("/files/{job_id}/{filename}")
async def get_file(job_id: str, filename: str):
    folder = DOWNLOAD_DIR / job_id
    file_path = folder / filename

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")

    return FileResponse(
        file_path,
        media_type="video/mp4",
        filename=filename
    )
