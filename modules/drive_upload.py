"""
modules/drive_upload.py — Google Drive upload integration.

Handles:
  - OAuth2 authentication with token caching (token_drive.json)
  - Creating / reusing a named folder in Drive (configurable via config.json)
  - Uploading files with chunked resumable uploads + live progress bar
  - Optional "anyone with link" sharing for each uploaded file
  - Returning shareable webViewLink for each uploaded file

Config keys (all optional, with defaults shown):
  drive_folder        : "Grok-{DD-MM-YYYY}"   — target folder name in Drive
  drive_make_public   : false                  — set anyone-with-link reader
  drive_parent_id     : null                   — existing parent folder ID to nest inside
"""

import io
import mimetypes
import os
from datetime import date

from modules.logger import console, print_info, print_success, print_error, print_warning

# ── Constants ────────────────────────────────────────────────────────────────

SCOPES = ["https://www.googleapis.com/auth/drive.file"]
CREDENTIALS_FILE = "credentials.json"
TOKEN_FILE = "token_drive.json"

# 5 MB chunks for resumable upload
_CHUNK_SIZE = 5 * 1024 * 1024

# Fallback MIME map for types mimetypes may not detect correctly
_MIME_FALLBACK = {
    ".mp4":  "video/mp4",
    ".mov":  "video/quicktime",
    ".avi":  "video/x-msvideo",
    ".webm": "video/webm",
    ".mkv":  "video/x-matroska",
    ".jpg":  "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png":  "image/png",
    ".webp": "image/webp",
    ".gif":  "image/gif",
    ".bmp":  "image/bmp",
}


# ── Internal helpers ─────────────────────────────────────────────────────────

def _detect_mime(file_path: str) -> str:
    """Return the MIME type for a file, falling back to octet-stream."""
    ext = os.path.splitext(file_path)[1].lower()
    if ext in _MIME_FALLBACK:
        return _MIME_FALLBACK[ext]
    mime, _ = mimetypes.guess_type(file_path)
    return mime or "application/octet-stream"


def _get_drive_service():
    """Authenticate and return a built Drive v3 API service object."""
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

    # Load cached token
    if os.path.exists(TOKEN_FILE):
        try:
            creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
        except Exception:
            creds = None

    # Refresh or re-authenticate
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                print_success("Drive token refreshed successfully.")
            except Exception as exc:
                print_warning(f"Token refresh failed ({exc}), re-authenticating …")
                creds = None

        if not creds:
            if not os.path.exists(CREDENTIALS_FILE):
                raise FileNotFoundError(
                    f"\n  '{CREDENTIALS_FILE}' not found!\n\n"
                    "  To enable Google Drive uploads:\n"
                    "  1. Go to https://console.cloud.google.com/\n"
                    "  2. Create a project and enable the Google Drive API\n"
                    "  3. Create OAuth 2.0 credentials (Desktop app)\n"
                    "  4. Download the JSON file and save it as 'credentials.json'\n"
                    "     in the same folder as grok_auto.py\n"
                )
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
            print_success("Drive OAuth completed — token saved.")

        # Persist the token
        with open(TOKEN_FILE, "w") as f:
            f.write(creds.to_json())

    return build("drive", "v3", credentials=creds)


def _get_or_create_folder(service, folder_name: str, parent_id: str | None = None) -> str:
    """
    Return the Drive folder ID for `folder_name`, creating it if absent.
    If `parent_id` is given, the folder is nested inside that parent.
    """
    query_parts = [
        f"name='{folder_name}'",
        "mimeType='application/vnd.google-apps.folder'",
        "trashed=false",
    ]
    if parent_id:
        query_parts.append(f"'{parent_id}' in parents")

    query = " and ".join(query_parts)
    results = service.files().list(q=query, fields="files(id, name)").execute()
    files = results.get("files", [])

    if files:
        folder_id = files[0]["id"]
        print_info(f"Using existing Drive folder: '{folder_name}' (id={folder_id})")
        return folder_id

    # Create new folder
    folder_meta: dict = {
        "name": folder_name,
        "mimeType": "application/vnd.google-apps.folder",
    }
    if parent_id:
        folder_meta["parents"] = [parent_id]

    folder = service.files().create(body=folder_meta, fields="id").execute()
    folder_id = folder["id"]
    print_success(f"Created Drive folder: '{folder_name}' (id={folder_id})")
    return folder_id


def _make_public(service, file_id: str) -> None:
    """Grant anyone-with-link reader access to a Drive file."""
    try:
        service.permissions().create(
            fileId=file_id,
            body={"role": "reader", "type": "anyone"},
        ).execute()
    except Exception as exc:
        print_warning(f"Could not set public permission for {file_id}: {exc}")


def _upload_single_file(
    service,
    file_path: str,
    folder_id: str,
    make_public: bool = False,
) -> str | None:
    """
    Upload one file to Drive using a chunked resumable upload.
    Shows a live progress bar during upload.
    Returns the webViewLink, or None on failure.
    """
    from googleapiclient.http import MediaFileUpload

    filename = os.path.basename(file_path)
    mime = _detect_mime(file_path)
    size_mb = os.path.getsize(file_path) / (1024 * 1024)

    print_info(f"Uploading: [bold]{filename}[/bold]  ({size_mb:.1f} MB, {mime})")

    try:
        media = MediaFileUpload(
            file_path,
            mimetype=mime,
            resumable=True,
            chunksize=_CHUNK_SIZE,
        )
        file_meta = {"name": filename, "parents": [folder_id]}

        request = service.files().create(
            body=file_meta,
            media_body=media,
            fields="id,name,webViewLink",
        )

        response = None
        while response is None:
            status, response = request.next_chunk()
            if status:
                pct = int(status.progress() * 100)
                bar_filled = pct // 5  # 20-char bar
                bar = "█" * bar_filled + "░" * (20 - bar_filled)
                console.print(
                    f"\r    [{bar}] {pct:3d}%", end="", highlight=False
                )

        console.print()  # newline after progress bar

        file_id = response.get("id", "")
        link = response.get("webViewLink", "")

        if make_public and file_id:
            _make_public(service, file_id)
            # Build a direct shareable link
            link = f"https://drive.google.com/file/d/{file_id}/view?usp=sharing"

        print_success(f"  ✓ Uploaded → {link}")
        return link

    except Exception as exc:
        console.print()  # newline in case progress bar was mid-line
        print_error(f"  ✗ Upload failed for '{filename}': {exc}")
        return None


# ── Public API ───────────────────────────────────────────────────────────────

def setup_drive_auth() -> bool:
    """
    Standalone helper: authenticate with Drive and verify the connection.
    Call this to test credentials before running a full batch.
    Returns True on success, False on failure.
    """
    print_info("Testing Google Drive authentication …")
    try:
        service = _get_drive_service()
        # Quick sanity check — list root folder
        service.files().list(pageSize=1, fields="files(id)").execute()
        print_success("Google Drive authentication successful! ✓")
        return True
    except FileNotFoundError as exc:
        print_error(str(exc))
        return False
    except Exception as exc:
        print_error(f"Drive auth test failed: {exc}")
        return False


def upload_to_drive(file_paths: list[str], config: dict) -> list[dict]:
    """
    Upload all files in `file_paths` to a Google Drive folder.

    Config keys used:
      drive_folder      (str)  — folder name; defaults to "Grok-DD-MM-YYYY"
      drive_parent_id   (str)  — parent folder ID to nest inside (optional)
      drive_make_public (bool) — make uploaded files publicly readable; default False

    Returns a list of {"file": path, "link": url_or_"upload_failed"} dicts.
    """
    folder_name: str = config.get(
        "drive_folder",
        f"Grok-{date.today().strftime('%d-%m-%Y')}",
    )
    parent_id: str | None = config.get("drive_parent_id") or None
    make_public: bool = bool(config.get("drive_make_public", False))

    print_info(f"Google Drive target folder: '{folder_name}'")
    if make_public:
        print_info("Files will be made publicly readable (anyone with link).")

    # Authenticate
    try:
        service = _get_drive_service()
    except FileNotFoundError as exc:
        print_error(str(exc))
        return []
    except Exception as exc:
        print_error(f"Drive authentication failed: {exc}")
        return []

    # Ensure destination folder exists
    try:
        folder_id = _get_or_create_folder(service, folder_name, parent_id)
    except Exception as exc:
        print_error(f"Could not create/find Drive folder: {exc}")
        return []

    results: list[dict] = []
    skipped = 0

    for fp in file_paths:
        if not os.path.exists(fp):
            print_warning(f"Skipping missing file: {fp}")
            skipped += 1
            continue

        link = _upload_single_file(service, fp, folder_id, make_public=make_public)
        results.append({"file": fp, "link": link or "upload_failed"})

    uploaded = sum(1 for r in results if r["link"] != "upload_failed")
    failed = len(results) - uploaded

    console.print()
    print_success(
        f"Drive upload complete: "
        f"[green]{uploaded} uploaded[/green]"
        + (f", [yellow]{failed} failed[/yellow]" if failed else "")
        + (f", [dim]{skipped} skipped[/dim]" if skipped else "")
        + f" — folder: '{folder_name}'"
    )

    return results


# ── In-memory upload (no local file required) ────────────────────────────────

def _upload_single_bytes(
    service,
    filename: str,
    data: bytes,
    mime: str,
    folder_id: str,
    make_public: bool = False,
) -> str | None:
    """
    Upload raw bytes straight to Drive using MediaIoBaseUpload.
    Shows a live progress bar. Returns the webViewLink, or None on failure.
    """
    from googleapiclient.http import MediaIoBaseUpload

    size_mb = len(data) / (1024 * 1024)
    print_info(f"Uploading (memory): [bold]{filename}[/bold]  ({size_mb:.1f} MB, {mime})")

    try:
        buf = io.BytesIO(data)
        media = MediaIoBaseUpload(
            buf,
            mimetype=mime,
            resumable=True,
            chunksize=_CHUNK_SIZE,
        )
        file_meta = {"name": filename, "parents": [folder_id]}

        request = service.files().create(
            body=file_meta,
            media_body=media,
            fields="id,name,webViewLink",
        )

        response = None
        while response is None:
            status, response = request.next_chunk()
            if status:
                pct = int(status.progress() * 100)
                bar_filled = pct // 5
                bar = "█" * bar_filled + "░" * (20 - bar_filled)
                console.print(
                    f"\r    [{bar}] {pct:3d}%", end="", highlight=False
                )

        console.print()

        file_id = response.get("id", "")
        link = response.get("webViewLink", "")

        if make_public and file_id:
            _make_public(service, file_id)
            link = f"https://drive.google.com/file/d/{file_id}/view?usp=sharing"

        print_success(f"  ✓ Uploaded (direct) → {link}")
        return link

    except Exception as exc:
        console.print()
        print_error(f"  ✗ In-memory upload failed for '{filename}': {exc}")
        return None


def upload_bytes_to_drive(
    items: list[tuple[str, bytes]],
    config: dict,
) -> list[dict]:
    """
    Upload (filename, bytes) pairs directly to Google Drive — no local file needed.

    Config keys used (same as upload_to_drive):
      drive_folder      (str)  — folder name; defaults to \"Grok-DD-MM-YYYY\"
      drive_parent_id   (str)  — parent folder ID to nest inside (optional)
      drive_make_public (bool) — make uploaded files publicly readable; default False

    Returns a list of {\"file\": filename, \"link\": url_or_\"upload_failed\"} dicts.
    """
    if not items:
        print_warning("No in-memory items to upload.")
        return []

    folder_name: str = config.get(
        "drive_folder",
        f"Grok-{date.today().strftime('%d-%m-%Y')}",
    )
    parent_id: str | None = config.get("drive_parent_id") or None
    make_public: bool = bool(config.get("drive_make_public", False))

    print_info(f"Google Drive target folder (direct): '{folder_name}'")
    if make_public:
        print_info("Files will be made publicly readable (anyone with link).")

    try:
        service = _get_drive_service()
    except FileNotFoundError as exc:
        print_error(str(exc))
        return []
    except Exception as exc:
        print_error(f"Drive authentication failed: {exc}")
        return []

    try:
        folder_id = _get_or_create_folder(service, folder_name, parent_id)
    except Exception as exc:
        print_error(f"Could not create/find Drive folder: {exc}")
        return []

    results: list[dict] = []

    for filename, data in items:
        ext = os.path.splitext(filename)[1].lower()
        mime = _MIME_FALLBACK.get(ext, "application/octet-stream")
        link = _upload_single_bytes(service, filename, data, mime, folder_id, make_public=make_public)
        results.append({"file": filename, "link": link or "upload_failed"})

    uploaded = sum(1 for r in results if r["link"] != "upload_failed")
    failed = len(results) - uploaded

    console.print()
    print_success(
        f"Drive direct-upload complete: "
        f"[green]{uploaded} uploaded[/green]"
        + (f", [yellow]{failed} failed[/yellow]" if failed else "")
        + f" — folder: '{folder_name}'"
    )

    return results
