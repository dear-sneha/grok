"""
modules/youtube_upload.py — YouTube video upload integration.

Handles:
  - OAuth2 authentication with token caching (token_youtube.json)
  - Chunked resumable video upload
  - Configurable title, description, privacy, tags, and category
  - Upload progress display
"""

import os

from modules.logger import console, print_info, print_success, print_error, print_warning

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",
]
CREDENTIALS_FILE = "credentials.json"
TOKEN_FILE = "token_youtube.json"


def _get_youtube_service():
    """Authenticate and return a built YouTube API service object."""
    try:
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build
    except ImportError as e:
        raise ImportError(
            "Google API libraries not installed. "
            "Run: pip install google-auth-oauthlib google-api-python-client"
        ) from e

    creds = None

    if os.path.exists(TOKEN_FILE):
        try:
            creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
        except Exception:
            creds = None

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                print_success("YouTube token refreshed.")
            except Exception:
                creds = None

        if not creds:
            if not os.path.exists(CREDENTIALS_FILE):
                raise FileNotFoundError(
                    f"'{CREDENTIALS_FILE}' not found. "
                    "Download it from Google Cloud Console > APIs & Services > Credentials."
                )
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
            print_success("YouTube OAuth completed. Token saved.")

        with open(TOKEN_FILE, "w") as f:
            f.write(creds.to_json())

    return build("youtube", "v3", credentials=creds)


def _upload_single_video(
    service,
    file_path: str,
    title: str,
    description: str,
    privacy: str,
    tags: list[str],
    category_id: str = "22",
) -> str | None:
    """
    Upload a single video to YouTube using a chunked resumable request.
    Returns the YouTube URL, or None on failure.
    """
    from googleapiclient.http import MediaFileUpload

    print_info(f"Uploading to YouTube: {os.path.basename(file_path)} …")
    try:
        body = {
            "snippet": {
                "title": title or os.path.basename(file_path),
                "description": description,
                "tags": tags,
                "categoryId": category_id,
            },
            "status": {
                "privacyStatus": privacy,
                "selfDeclaredMadeForKids": False,
            },
        }

        media = MediaFileUpload(file_path, mimetype="video/mp4", resumable=True, chunksize=1024 * 1024 * 5)
        request = service.videos().insert(part="snippet,status", body=body, media_body=media)

        response = None
        while response is None:
            status, response = request.next_chunk()
            if status:
                pct = int(status.progress() * 100)
                console.print(f"\r    Upload: [bold]{pct}%[/bold]     ", end="")

        console.print()
        video_id = response.get("id", "")
        yt_url = f"https://youtu.be/{video_id}" if video_id else ""
        print_success(f"Uploaded to YouTube → {yt_url}")
        return yt_url

    except Exception as exc:
        print_error(f"YouTube upload failed for '{os.path.basename(file_path)}': {exc}")
        return None


def upload_to_youtube(file_paths: list[str], config: dict) -> list[dict]:
    """
    Upload all MP4 files to YouTube using settings from config.
    Non-MP4 files are skipped with a warning.

    Returns a list of {file, url} dicts.
    """
    privacy: str = config.get("youtube_privacy", "private")
    description: str = config.get("youtube_description", "Generated with Grok Automation.")
    tags: list = config.get("youtube_tags", ["AI", "Grok", "automation"])

    print_info("Starting YouTube upload …")

    try:
        service = _get_youtube_service()
    except Exception as exc:
        print_error(f"YouTube auth failed: {exc}")
        return []

    results = []
    for fp in file_paths:
        if not fp.lower().endswith(".mp4"):
            print_warning(f"Skipping non-MP4 file (YouTube only accepts MP4): {fp}")
            continue
        if not os.path.exists(fp):
            print_warning(f"Skipping missing file: {fp}")
            continue

        title = os.path.splitext(os.path.basename(fp))[0].replace("_", " ").replace("-", " ")
        url = _upload_single_video(service, fp, title, description, privacy, tags)
        results.append({"file": fp, "url": url or "upload_failed"})

    uploaded = sum(1 for r in results if r["url"] != "upload_failed")
    print_success(f"YouTube upload complete: {uploaded}/{len(results)} videos.")
    return results
