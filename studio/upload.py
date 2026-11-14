"""Step 6 (optional): upload to YouTube through the official Data API.

Important: YouTube locks videos uploaded from an *unverified* API project as private, and
they can never be made public. So keep UPLOAD_MODE=manual (default) until your Google Cloud
project passes YouTube's free API audit (https://support.google.com/youtube/contact/yt_api_form).
After approval, set UPLOAD_MODE=api and the pipeline uploads straight into YouTube Studio.
"""
import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import config

SCOPES = ["https://www.googleapis.com/auth/youtube.upload",
          "https://www.googleapis.com/auth/youtube"]


def _client():
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    creds = Credentials(None, refresh_token=config.YT_REFRESH_TOKEN,
                        client_id=config.YT_CLIENT_ID, client_secret=config.YT_CLIENT_SECRET,
                        token_uri="https://oauth2.googleapis.com/token", scopes=SCOPES)
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def upload(video: Path, thumb: Path, title: str, description: str, tags: list,
           captions: Path | None = None) -> str:
    from googleapiclient.http import MediaFileUpload
    yt = _client()
    body = {
        "snippet": {"title": title[:100], "description": description[:4900],
                    "tags": tags[:30], "categoryId": config.YT_CATEGORY_ID,
                    "defaultLanguage": "en", "defaultAudioLanguage": "en"},
        "status": {"privacyStatus": config.YT_PRIVACY, "selfDeclaredMadeForKids": False,
                   "embeddable": True},
    }
    if config.YT_PUBLISH_DELAY_HOURS > 0:   # YouTube flips it to public at publishAt
        when = datetime.now(timezone.utc) + timedelta(hours=config.YT_PUBLISH_DELAY_HOURS)
        body["status"]["privacyStatus"] = "private"
        body["status"]["publishAt"] = when.strftime("%Y-%m-%dT%H:%M:%SZ")
        print(f"   scheduled to go public at {body['status']['publishAt']}")
    req = yt.videos().insert(part="snippet,status", body=body,
                             media_body=MediaFileUpload(str(video), chunksize=8 * 1024 * 1024,
                                                        resumable=True, mimetype="video/mp4"))
    resp = None
    while resp is None:
        status, resp = req.next_chunk()
        if status:
            print(f"   upload {int(status.progress() * 100)}%")
    vid = resp["id"]
    try:
        if thumb:
            yt.thumbnails().set(videoId=vid, media_body=MediaFileUpload(str(thumb))).execute()
    except Exception as e:   # custom thumbnails need a phone-verified channel
        print(f"   ! thumbnail not set ({e}); verify your channel at youtube.com/verify")
    if captions and captions.exists():
        try:
            yt.captions().insert(part="snippet", body={"snippet": {
                "videoId": vid, "language": "en", "name": "English", "isDraft": False}},
                media_body=MediaFileUpload(str(captions), mimetype="application/octet-stream")).execute()
        except Exception as e:
            print(f"   ! captions not uploaded: {str(e)[:150]}")
    return vid


def upload_folder(folder: Path) -> str:
    """Upload a finished video folder (any kind) with its metadata, a random one of its thumbnails
    and its captions. Writes youtube_id.txt next to it and returns the video id."""
    folder = Path(folder)
    meta = json.loads((folder / "metadata.json").read_text())
    video = folder / meta.get("video_file", "video.mp4")
    if not video.exists():
        video = sorted(folder.glob("*.mp4"))[0]
    thumbs = sorted(folder.glob("*thumbnail*.jpg"))      # no Pillow needed (the upload workflow lacks it)
    thumb = random.choice(thumbs) if thumbs else None
    print(f"   uploading to YouTube (thumbnail: {thumb.name if thumb else 'none'})")
    vid = upload(video, thumb, meta["title"], meta.get("description", ""), meta.get("tags", []),
                 folder / "captions.srt")
    (folder / "youtube_id.txt").write_text(vid)
    print(f"   uploaded: https://youtu.be/{vid}")
    return vid
