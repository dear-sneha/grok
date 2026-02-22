"""
modules/downloader.py — File downloading and saving for Grok Automation.

Handles:
  - Intercepting Playwright download events (most reliable for video)
  - Direct HTTP fetch of video src URLs
  - Decoding base64 data-URLs for images
  - Generating organised output file paths: ./output/DD-MM/N_slug_a.ext
"""

import os
import re
import base64
import time
from datetime import date

import httpx
from playwright.sync_api import Page

from modules.logger import console, print_info, print_success, print_warning, print_error

# ─── Path helpers ─────────────────────────────────────────────────────────────

ALPHABET = "abcdefghijklmnopqrstuvwxyz"


def slugify(text: str, max_len: int = 50) -> str:
    """Convert a prompt string into a safe filesystem slug."""
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"\s+", "-", text.strip())
    return text[:max_len].rstrip("-").lower()


def get_output_path(
    config: dict,
    prompt_index: int,
    prompt_text: str,
    suffix_index: int,
    ext: str,
) -> str:
    """
    Build a file path like:
      ./output/20-02/1_cinematic-sunrise_a.mp4
    Creates parent directories automatically.
    """
    date_str = date.today().strftime("%d-%m")
    slug = slugify(prompt_text)
    letter = ALPHABET[suffix_index % len(ALPHABET)]
    filename = f"{prompt_index}_{slug}_{letter}.{ext}"

    folder = os.path.join(config.get("output_folder", "./output"), date_str)
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, filename)


# ─── Download strategies ──────────────────────────────────────────────────────

def download_via_button(
    page: Page,
    download_selector: str,
    output_path: str,
    timeout: int = 30000,
) -> bool:
    """
    Strategy A: Click the download button and capture the Playwright download event.
    Most reliable for files served with Content-Disposition headers.
    """
    try:
        with page.expect_download(timeout=timeout) as dl_info:
            page.click(download_selector, timeout=5000)
        dl = dl_info.value
        dl.save_as(output_path)
        print_success(f"Downloaded (via button): {os.path.basename(output_path)}")
        return True
    except Exception as exc:
        print_error(f"Button download failed: {exc}")
        return False


def download_blob_via_js(page, blob_url: str, output_path: str) -> bool:
    """
    Strategy B0: Download a blob: URL using JavaScript inside the browser page.
    blob: URLs are only accessible inside the browser context that created them.
    We fetch the blob with JS, convert to base64, return to Python, then write to disk.
    """
    try:
        b64 = page.evaluate("""
            async (blobUrl) => {
                const resp = await fetch(blobUrl);
                const buf  = await resp.arrayBuffer();
                const bytes = new Uint8Array(buf);
                let binary = '';
                for (let i = 0; i < bytes.byteLength; i++) {
                    binary += String.fromCharCode(bytes[i]);
                }
                return btoa(binary);
            }
        """, blob_url)
        if not b64:
            print_warning("Blob JS fetch returned empty data")
            return False
        raw = base64.b64decode(b64)
        with open(output_path, "wb") as f:
            f.write(raw)
        size_kb = len(raw) // 1024
        print_success(f"Downloaded (blob→JS) {size_kb} KB → {os.path.basename(output_path)}")
        return True
    except Exception as exc:
        print_error(f"Blob JS download failed: {exc}")
        return False


def download_via_url(
    src_url: str,
    output_path: str,
    referer: str = "https://grok.com/",
    timeout: int = 60,
    page=None,  # optional Playwright Page for authenticated / blob downloads
) -> bool:
    """
    Strategy B: Fetch media URL.
    - blob: URLs  → JS inside the browser (only way to read them)
    - http: URLs  → Playwright session (carries cookies) then httpx fallback
    """
    # blob: URLs can ONLY be read inside the browser that created them
    if src_url.startswith("blob:"):
        if page is None:
            print_error("Cannot download blob: URL without a page reference")
            return False
        return download_blob_via_js(page, src_url, output_path)

    # Strategy B1: Playwright request (carries session cookies — avoids 403)
    if page is not None:
        try:
            response = page.context.request.get(
                src_url,
                headers={"Referer": referer},
                timeout=timeout * 1000,
            )
            if response.ok:
                body = response.body()
                with open(output_path, "wb") as f:
                    f.write(body)
                size_kb = len(body) // 1024
                print_success(f"Downloaded (session) {size_kb} KB → {os.path.basename(output_path)}")
                return True
            else:
                print_warning(f"Session fetch returned HTTP {response.status} — trying httpx")
        except Exception as exc:
            print_warning(f"Session fetch failed ({exc}) — trying httpx")

    # Strategy B2: plain httpx (public CDN)
    try:
        headers = {
            "Referer": referer,
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
        }
        with httpx.stream("GET", src_url, headers=headers, timeout=timeout, follow_redirects=True) as resp:
            resp.raise_for_status()
            with open(output_path, "wb") as f:
                for chunk in resp.iter_bytes(chunk_size=8192):
                    f.write(chunk)
        size_kb = os.path.getsize(output_path) // 1024
        print_success(f"Downloaded (httpx) {size_kb} KB → {os.path.basename(output_path)}")
        return True
    except Exception as exc:
        print_error(f"URL download failed: {exc}")
        return False


def save_base64_image(data_url: str, output_path: str) -> bool:
    """
    Strategy C: Decode a base64 data: URL and write raw bytes to disk.
    Used for images returned as data:image/jpeg;base64,... src values.
    """
    try:
        if "," not in data_url:
            print_error("Invalid data URL format (no comma separator).")
            return False
        _, encoded = data_url.split(",", 1)
        image_bytes = base64.b64decode(encoded)
        with open(output_path, "wb") as f:
            f.write(image_bytes)
        size_kb = len(image_bytes) // 1024
        print_success(f"Saved base64 image {size_kb} KB → {os.path.basename(output_path)}")
        return True
    except Exception as exc:
        print_error(f"Base64 image save failed: {exc}")
        return False


# ─── Media extraction helpers ─────────────────────────────────────────────────

def extract_video_src(page: Page, video_selector: str = "video[src]") -> str | None:
    """Return the src from the first visible <video> or <video><source> element."""
    try:
        # Direct src on <video>
        for v in page.query_selector_all("video"):
            src = v.get_attribute("src") or ""
            if src.startswith("http") or src.startswith("blob:"):
                return src
            # Check <source> child
            source_el = v.query_selector("source[src]")
            if source_el:
                src = source_el.get_attribute("src") or ""
                if src.startswith("http") or src.startswith("blob:"):
                    return src
    except Exception:
        pass
    return None


def extract_image_data_urls(page: Page, min_size: int = 130_000) -> list[str]:
    """
    Return a list of base64 data-URLs from <img> elements whose src is
    sufficiently large to be a generated image (not thumbnails/icons).
    """
    try:
        imgs = page.query_selector_all("img[src^='data:image']")
        result = []
        for img in imgs:
            src = img.get_attribute("src") or ""
            if len(src) >= min_size:
                result.append(src)
        return result
    except Exception:
        return []


# ─── High-level save function ─────────────────────────────────────────────────

def save_media(
    page: Page,
    mode: str,
    config: dict,
    prompt_index: int,
    prompt_text: str,
    selectors: dict,
    media_elements: list,
) -> list[str]:
    """
    Attempt to save all detected media elements to disk.

    Returns a list of saved file paths.
    """
    saved = []

    for i, elem in enumerate(media_elements):
        is_video = "ToVideo" in mode
        ext = "mp4" if is_video else "jpg"
        output_path = get_output_path(config, prompt_index, prompt_text, i, ext)

        if is_video:
            success = False

            # Strategy 1: get src directly from the element and download with session cookies
            src = None
            try:
                src = elem.get_attribute("src") or ""
                # If it's a <source> child, it already has the src
                # If it's a <video> with a <source> child, look inside
                if not src or not (src.startswith("http") or src.startswith("blob:")):
                    src = None
                    source_child = elem.query_selector("source[src]")
                    if source_child:
                        src = source_child.get_attribute("src") or ""
            except Exception:
                pass
            if not src or not (src.startswith("http") or src.startswith("blob:")):
                src = extract_video_src(page)

            if src and src.startswith("http"):
                # Pass page so it uses the browser's session cookies (avoids 403)
                success = download_via_url(src, output_path, page=page)

            # Strategy 2: click the download button (Playwright intercepts the download)
            if not success:
                dl_selector = selectors.get("downloadButton", "button[aria-label='Download'], a[download]")
                if dl_selector:
                    success = download_via_button(page, dl_selector, output_path)

            if success:
                saved.append(output_path)
            else:
                print_error(f"Could not download video for prompt #{prompt_index}, item {i + 1}")

        else:
            # Image
            src = None
            try:
                src = elem.get_attribute("src")
            except Exception:
                pass
            if src and src.startswith("data:image"):
                if save_base64_image(src, output_path):
                    saved.append(output_path)
            elif src and src.startswith("http"):
                # Pass page for session cookies
                if download_via_url(src, output_path, page=page):
                    saved.append(output_path)
            else:
                print_error(f"Unknown image src format for prompt #{prompt_index}, item {i + 1}")

    return saved
