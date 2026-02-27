"""
modules/grok_ui.py — Full Grok UI automation using confirmed live selectors.

Selectors discovered by direct inspection of grok.com/imagine (Feb 2026).
All remote config fetching removed — uses only local confirmed selectors.
"""

import re
import os
import time  # FIX: was accidentally removed, needed by wait_for_media + run_automation

from playwright.sync_api import Page, ElementHandle

from modules.logger import (
    console,
    print_info,
    print_success,
    print_warning,
    print_error,
    print_prompt_status,
)
from modules.downloader import save_media, fetch_media_bytes

# ─── Confirmed live selectors (inspected Feb 2026) ────────────────────────────

DEFAULT_SELECTORS: dict = {
    # Mode selector trigger
    "modeSelectTrigger": "#model-select-trigger",

    # Prompt input — TipTap ProseMirror contenteditable div
    "promptContentEditable": ".tiptap.ProseMirror[contenteditable='true']",

    # Submit / Send button — Grok uses aria-label="Send" on the arrow button
    # FIX: was too broad (matched every SVG button). Now precise.
    "submitButton": (
        "button[aria-label='Send'], "
        "button[aria-label='Submit'], "
        "button[type='submit']"
    ),

    # File upload (hidden input)
    "fileInput": "input[type='file'][name='files']",

    # Progress SVG (when generating)
    "percentageSvg": "circle[stroke-dasharray]",

    # Generated content
    "generatedImage": "img[alt='Generated image'], img[src*='imagine-public']",
    "generatedVideo": "video[src]",

    # Download button
    "downloadButton": "button[aria-label='Download'], a[download], button:has(svg[aria-label='Download'])",

    # Share button
    "shareButton": "button[aria-label='Share']",

    # Main article
    "mainArticle": "article",
}


def fetch_remote_selectors() -> dict:
    """Returns local confirmed selectors only. Remote fetching disabled."""
    return DEFAULT_SELECTORS


# ─── Low-level interaction helpers ────────────────────────────────────────────

def _try_selector(page: Page, selector: str, timeout_ms: int = 4000) -> ElementHandle | None:
    """Try a single CSS selector, return element if visible, else None."""
    try:
        page.wait_for_selector(selector, state="visible", timeout=timeout_ms)
        el = page.query_selector(selector)
        if el and el.is_visible():
            return el
    except Exception:
        pass
    return None


def _first_visible(page: Page, compound_selector: str, timeout_ms: int = 8000) -> ElementHandle | None:
    """Try each comma-separated part of a compound selector, return first visible."""
    parts = [p.strip() for p in compound_selector.split(",") if p.strip()]
    per_part = max(timeout_ms // max(len(parts), 1), 1500)
    for part in parts:
        el = _try_selector(page, part, per_part)
        if el:
            return el
    return None


def safe_click(page: Page, compound_selector: str, label: str = "", timeout_ms: int = 8000) -> bool:
    """Find → scroll into view → hover → click. Returns True on success."""
    el = _first_visible(page, compound_selector, timeout_ms)
    if not el:
        print_warning(f"Cannot click — element not found: {label or compound_selector[:60]}")
        return False
    try:
        el.scroll_into_view_if_needed()
        el.hover()
        page.wait_for_timeout(150)
        el.click()
        page.wait_for_timeout(400)
        return True
    except Exception as exc:
        print_warning(f"Click failed [{label}]: {exc}")
        return False


# ─── Prompt entry ─────────────────────────────────────────────────────────────

def type_prompt(page: Page, selector: str, text: str) -> bool:
    """
    Enter text into TipTap ProseMirror contenteditable.
    Waits for UI stability after mode switch before typing.
    """
    # Wait for UI to stabilise after mode switch
    page.wait_for_timeout(1500)

    # Always prefer the confirmed stable selector
    stable = ".tiptap.ProseMirror[contenteditable='true']"
    combined = f"{stable}, {selector}" if selector and selector != stable else stable
    el = _first_visible(page, combined, timeout_ms=10000)

    if not el:
        print_warning("Prompt box not found")
        return False

    try:
        el.click()
        page.wait_for_timeout(400)

        # JS insert to properly trigger ProseMirror's internal state
        page.evaluate("""([el, text]) => {
            el.focus();
            el.innerHTML = '';
            document.execCommand('insertText', false, text);
            el.dispatchEvent(new InputEvent('input', { bubbles: true }));
            el.dispatchEvent(new Event('change', { bubbles: true }));
        }""", [el, text])

        page.wait_for_timeout(600)

        # Verify text landed; fallback to keyboard typing if not
        val = ""
        try:
            val = el.inner_text() or ""
        except Exception:
            pass
        if len(val.strip()) < 2:
            el.click()
            page.keyboard.press("Control+a")
            page.keyboard.press("Backspace")
            page.keyboard.type(text, delay=20)
            page.wait_for_timeout(400)

        return True
    except Exception as exc:
        print_warning(f"Could not type prompt: {exc}")
        return False


# ─── Image upload ─────────────────────────────────────────────────────────────

def upload_image(page: Page, file_path: str, file_input_selector: str) -> bool:
    """Set files on the hidden file input."""
    if not file_path or not os.path.exists(file_path):
        print_warning(f"Image file not found: {file_path}")
        return False
    try:
        page.set_input_files(file_input_selector, file_path)
        page.wait_for_timeout(1500)
        print_info(f"Uploaded image: {os.path.basename(file_path)}")
        return True
    except Exception as exc:
        print_warning(f"Image upload failed: {exc}")
        return False


# ─── Dropdown helpers ─────────────────────────────────────────────────────────

def _is_menu_open(page: Page) -> bool:
    """
    Check if the Grok dropdown menu is currently visible.
    FIX: is_visible() does not accept a timeout param — use try/except instead.
    """
    try:
        loc = page.locator("[role='menu']")
        return loc.count() > 0 and loc.first.is_visible()
    except Exception:
        return False


def _click_dropdown_item(page: Page, text: str, label: str = "") -> bool:
    """
    Click a Radix collection item (Video/Image mode).
    Iterates ALL [data-radix-collection-item] items and matches by inner_text.
    """
    try:
        items = page.locator("[role='menuitem'][data-radix-collection-item]")
        count = items.count()

        for i in range(count):
            item = items.nth(i)
            try:
                item_text = (item.inner_text() or "").strip()
            except Exception:
                continue
            # "VideoGenerate a video" → contains "video"
            if text.lower() in item_text.lower():
                item.scroll_into_view_if_needed()
                item.click(timeout=5000)
                page.wait_for_timeout(600)
                print_info(f"Clicked menu item: {label or text}")
                return True

    except Exception as exc:
        print_warning(f"Error clicking dropdown item '{text}': {exc}")

    print_warning(f"Dropdown item not found: {label or text}")
    return False


def _click_button_in_section(page: Page, section_text: str, button_text: str) -> bool:
    """
    Click a button inside a settings section (e.g. 'Video Duration', '6s').

    Strategy based on actual Grok UI structure (Feb 2026):
      1. Find div[role='group'] that contains a <p> with the section heading (e.g., 'Video Duration')
      2. Within that group, find button[aria-label=button_text] (most reliable)
      3. Fall back to button with matching text content
      4. Use force=True click to bypass visibility/overlap issues

    HTML structure: <div role="group"><p>Video Duration</p><div class="flex flex-row gap-0"><button aria-label="6s">...
    """
    try:
        # Step 1: Find the section group by its <p> heading
        # Use a more flexible approach: find the <p> with section text, then go to parent group
        section_group = page.locator("div[role='group']").filter(
            has=page.locator("p", has_text=re.compile(re.escape(section_text), re.I))
        )

        if section_group.count() == 0:
            print_warning(f"Section group not found: {section_text}")
            return False

        sec = section_group.first

        # Step 2: Try aria-label match first (most reliable for duration/resolution)
        # This handles: aria-label="6s", aria-label="10s", aria-label="720p", etc.
        target = sec.locator(f"button[aria-label='{button_text}']")

        # Step 3: Fall back to text content match (for aspect ratio buttons with text)
        if target.count() == 0:
            target = sec.locator("button").filter(
                has_text=re.compile(rf"^{re.escape(button_text)}$", re.I)
            )

        if target.count() > 0:
            page.wait_for_timeout(200)
            target.first.click(force=True, timeout=5000)
            page.wait_for_timeout(600)
            print_info(f"Set {section_text}: {button_text}")
            return True

        print_warning(f"Button '{button_text}' not found in section '{section_text}'")

    except Exception as exc:
        print_warning(f"Error in _click_button_in_section ({section_text}={button_text}): {exc}")

    print_warning(f"Could not set {section_text}={button_text}")
    return False


# ─── Mode configuration ───────────────────────────────────────────────────────

def configure_generation_mode(page: Page, config: dict, prompt_entry: dict, selectors: dict):
    """
    Open the model-select dropdown and set Duration, Resolution, Aspect Ratio, Mode.

    Grok's Radix dropdown CLOSES after each button click inside it.
    We re-open it before every step using ensure_menu_open().
    """
    mode: str          = config.get("mode", "textToVideo")
    aspect_ratio: str  = config.get("aspect_ratio", "16:9")
    video_length: str  = config.get("video_length", "6s")
    video_quality: str = config.get("video_quality", "720p")
    images: list       = prompt_entry.get("images", [])
    is_video           = "ToVideo" in mode or mode.lower().startswith("video")

    print_info(f"Configuring mode → {mode}")
    trigger_sel = selectors.get("modeSelectTrigger", "#model-select-trigger")

    def ensure_menu_open() -> bool:
        """Re-open the dropdown if it has closed."""
        if not _is_menu_open(page):
            print_info("Menu closed — re-opening …")
            if not safe_click(page, trigger_sel, "Model select trigger", timeout_ms=5000):
                return False
            page.wait_for_timeout(700)
            # Wait until at least one menu item/group is present
            try:
                page.wait_for_selector("[role='group'], [role='menuitemradio']", state="visible", timeout=3000)
            except Exception:
                pass
        return True

    # 1. Duration
    if is_video:
        if ensure_menu_open():
            _click_button_in_section(page, "Video Duration", video_length)

    # 2. Resolution
    if is_video:
        if ensure_menu_open():
            _click_button_in_section(page, "Video Resolution", video_quality)

    # 3. Aspect Ratio
    if ensure_menu_open():
        _click_button_in_section(page, "Aspect Ratio", aspect_ratio)

    # 4. Mode (Video / Image radio button)
    # Mode buttons use role="menuitemradio" with aria-checked="true/false"
    if ensure_menu_open():
        mode_text = "Video" if is_video else "Image"
        try:
            # Find the radio button that contains the mode text (Image or Video)
            mode_btn = page.locator(f"[role='menuitemradio']:has-text('{mode_text}')").first
            if mode_btn.is_visible():
                # Check if already selected
                is_checked = mode_btn.get_attribute("aria-checked") == "true"
                if not is_checked:
                    mode_btn.click(timeout=5000)
                    page.wait_for_timeout(600)
                    print_info(f"Set Mode: {mode_text}")
                else:
                    print_info(f"Mode already set to: {mode_text}")
            else:
                print_warning(f"Mode button '{mode_text}' not found or not visible")
        except Exception as exc:
            print_warning(f"Error setting mode to {mode_text}: {exc}")
            # Fallback to old method
            _click_dropdown_item(page, mode_text, f"{mode_text} mode")

    # 5. Image upload (imageToVideo / imageToImage)
    if images and any(k in mode for k in ("imageToVideo", "imageToImage", "componentsToVideo")):
        file_sel = selectors.get("fileInput", "input[type='file'][name='files']")
        for img_path in images:
            upload_image(page, img_path, file_sel)

    # Close the menu if still open (Escape is safe)
    try:
        if _is_menu_open(page):
            page.keyboard.press("Escape")
            page.wait_for_timeout(300)
    except Exception:
        pass


# ─── Progress tracking ────────────────────────────────────────────────────────

def get_generation_progress(page: Page, selectors: dict) -> int:
    """
    Read SVG stroke-dasharray / stroke-dashoffset to estimate generation %.
    """
    try:
        svg_sel = selectors.get("percentageSvg", "circle[stroke-dasharray]")
        elements = page.query_selector_all(svg_sel)
        for el in elements:
            da = el.get_attribute("stroke-dasharray") or ""
            do = el.get_attribute("stroke-dashoffset") or ""
            parts = re.split(r"[\s,]+", da.strip())
            if parts and parts[0]:
                total  = float(parts[0])
                offset = float(do.strip()) if do.strip() else 0.0
                if total > 0:
                    return max(0, min(round(100 * (1 - offset / total)), 100))
    except Exception:
        pass
    return 0


# ─── Media detection ──────────────────────────────────────────────────────────

def _collect_videos(page: Page) -> list:
    """
    Find video elements in the LATEST message (last <article>).
    """
    try:
        # Target the last article (most recent message)
        articles = page.query_selector_all("article")
        if not articles:
            return []
        last_article = articles[-1]
        
        found = []
        # Direct http src
        for v in last_article.query_selector_all("video[src]"):
            src = v.get_attribute("src") or ""
            if src.startswith("http") or src.startswith("blob:"):
                found.append(v)
        # <source> child approach
        for s in last_article.query_selector_all("video source[src]"):
            src = s.get_attribute("src") or ""
            if src.startswith("http") or src.startswith("blob:"):
                found.append(s)
        return found
    except Exception:
        return []


def _collect_images(page: Page) -> list:
    """Find completed generated images in the LATEST message."""
    try:
        articles = page.query_selector_all("article")
        if not articles:
            return []
        last_article = articles[-1]

        found = []
        # CDN images
        for img in last_article.query_selector_all("img[alt='Generated image'], img[src*='imagine-public']"):
            src = img.get_attribute("src") or ""
            if src.startswith("https://imagine-public"):
                found.append(img)
        # Fallback: large base64 images
        if not found:
            for img in last_article.query_selector_all("img[src^='data:image']"):
                src = img.get_attribute("src") or ""
                if len(src) >= 100_000:
                    found.append(img)
        return found
    except Exception:
        return []


def wait_for_media(
    page: Page,
    mode: str,
    output_count: int,
    selectors: dict,
    timeout_seconds: int = 360,
) -> list:
    """
    Poll until generated media is ready.

    Key fix: When Grok finishes, the progress SVG *disappears* (resets to 0).
    We track this: once SVG was seen and then vanishes, we know generation is done
    and wait a few seconds for the video/image element to render.
    """
    is_video = "ToVideo" in mode or mode.lower().startswith("video")
    print_info("Waiting for generation …")

    # ── Phase 1: wait for generation to START (article or progress SVG appears) ──
    svg_sel = "circle[stroke-dasharray], svg[stroke-dasharray]"
    for _ in range(20):
        article = page.query_selector("article")
        prog    = page.query_selector(svg_sel)
        if article or prog:
            break
        time.sleep(2)

    # ── Phase 2: poll — track progress AND detect SVG disappearing ─────────────
    last_pct      = -1
    svg_was_seen  = False   # True once we've seen the progress SVG
    deadline      = time.time() + timeout_seconds

    while time.time() < deadline:
        pct = get_generation_progress(page, selectors)

        # Track whether the SVG existed at some point
        if pct > 0:
            svg_was_seen = True

        if pct != last_pct:
            bar = "█" * (pct // 5) + "░" * (20 - pct // 5)
            console.print(f"\r  ⏳ [{bar}] {pct:3d}%    ", end="", highlight=False)
            last_pct = pct

        # ── Check if generation is DONE ──────────────────────────────────────
        # Grok signals completion by: SVG disappearing OR media element appearing
        svg_gone = svg_was_seen and pct == 0
        if svg_gone:
            console.print()
            print_info("Progress SVG gone — generation complete, collecting media …")
            # Give Grok 4s to render the video/image element
            time.sleep(4)

        if is_video:
            vids = _collect_videos(page)
            if len(vids) >= output_count:
                console.print()
                print_success(f"Video generation done — {len(vids)} video(s) found.")
                return vids
            if svg_gone and vids:
                # Partial — return what we have
                console.print()
                print_success(f"Video generation done — {len(vids)} video(s) collected.")
                return vids
        else:
            imgs = _collect_images(page)
            if len(imgs) >= output_count:
                console.print()
                print_success(f"Image generation done — {len(imgs)} image(s) found.")
                return imgs
            if svg_gone and imgs:
                console.print()
                print_success(f"Image generation done — {len(imgs)} image(s) collected.")
                return imgs

        if svg_gone:
            # SVG gone but no media found yet — keep polling a bit more
            # Reset so we don't trigger this block every loop
            svg_was_seen = False

        time.sleep(3)

    console.print()
    print_warning("Generation timeout — collecting any available media …")
    if is_video:
        return _collect_videos(page)
    else:
        return _collect_images(page)



# ─── Single prompt runner ─────────────────────────────────────────────────────

def run_single_prompt(
    page: Page,
    prompt_entry: dict,
    prompt_index: int,
    config: dict,
    selectors: dict,
) -> dict:
    """Run one generation job. Returns a result dict."""
    prompt_text: str = prompt_entry.get("prompt", "")
    mode: str        = config.get("mode", "textToVideo")
    output_count     = config.get("output_count", 1)

    result = {
        "index":       prompt_index,
        "prompt":      prompt_text,
        "status":      "failed",
        "saved_files": [],
        "drive_links": [],
        "error":       None,
    }

    try:
        # 1. Navigate to imagine page
        page.goto("https://grok.com/imagine", wait_until="domcontentloaded", timeout=30_000)
        page.wait_for_timeout(2500)

        # 2. Configure mode settings
        configure_generation_mode(page, config, prompt_entry, selectors)

        # 3. Type the prompt
        prompt_sel = selectors.get("promptContentEditable", ".tiptap.ProseMirror[contenteditable='true']")
        print_info(f"Entering prompt: {prompt_text[:70]}")
        if not type_prompt(page, prompt_sel, prompt_text):
            result["error"] = "Could not enter prompt"
            return result

        page.wait_for_timeout(800)

        # 4. Submit
        print_info("Submitting prompt …")

        # Focus the prompt box first so Enter key lands correctly
        prompt_el = _first_visible(page, ".tiptap.ProseMirror[contenteditable='true']", timeout_ms=3000)
        if prompt_el:
            prompt_el.focus()
            page.wait_for_timeout(300)

        # Try clicking the Send button
        submit_sel = selectors.get("submitButton", "button[aria-label='Send']")
        submit_btn = _first_visible(page, submit_sel, timeout_ms=3000)

        submitted = False
        if submit_btn:
            try:
                if submit_btn.is_enabled():
                    submit_btn.click()
                    submitted = True
                    print_info("Clicked Send button")
            except Exception:
                pass

        if not submitted:
            # Fallback: Enter key in the prompt box
            print_warning("Send button not found/disabled — using Enter key")
            page.keyboard.press("Enter")
            submitted = True

        print_info("Prompt submitted — waiting for generation …")
        page.wait_for_timeout(5000)

        # 5. Wait for media
        media = wait_for_media(
            page, mode, output_count, selectors,
            timeout_seconds=config.get("generation_timeout_seconds", 360),
        )

        if not media:
            result["error"] = "No media detected after generation"
            return result

        # 6. Save / upload files
        no_local = config.get("no_local_save", False) and config.get("auto_upload_drive", False)

        if no_local:
            # ── Direct-to-Drive path: no disk writes ──────────────────────────
            print_info("Direct-to-Drive mode: fetching media into memory …")
            items = fetch_media_bytes(page, mode, prompt_index, prompt_text, media)
            if items:
                from modules.drive_upload import upload_bytes_to_drive
                print_info("Streaming to Google Drive …")
                drive_results = upload_bytes_to_drive(items, config)
                result["drive_links"] = [r["link"] for r in drive_results]
                result["status"]      = "done" if any(r["link"] != "upload_failed" for r in drive_results) else "failed"
                if result["status"] == "failed":
                    result["error"] = "All direct Drive uploads failed"
            else:
                result["error"] = "Media detected but in-memory fetch failed"
        else:
            # ── Normal path: save to disk, then upload immediately ────────────
            saved = save_media(page, mode, config, prompt_index, prompt_text, selectors, media)
            result["saved_files"] = saved
            result["status"]      = "done" if saved else "failed"
            if not saved:
                result["error"] = "Media detected but download failed"

            # Upload to Drive right after each prompt (don't wait for all 149 to finish)
            if saved and config.get("auto_upload_drive"):
                try:
                    from modules.drive_upload import upload_to_drive
                    print_info(f"Uploading {len(saved)} file(s) to Google Drive …")
                    drive_results = upload_to_drive(saved, config)
                    result["drive_links"] = [r["link"] for r in drive_results]
                except Exception as exc:
                    print_error(f"Drive upload failed for prompt #{prompt_index}: {exc}")


    except Exception as exc:
        result["error"] = str(exc)
        print_error(f"Prompt #{prompt_index} exception: {exc}")

    return result


# ─── Batch runner ─────────────────────────────────────────────────────────────

def run_automation(page: Page, prompts: list, config: dict) -> list:
    """Process all prompts with retry logic and inter-prompt delays."""
    selectors   = fetch_remote_selectors()
    max_retries = config.get("max_retries", 2)
    delay       = config.get("prompt_delay_seconds", 3)
    total       = len(prompts)
    results     = []

    for idx, entry in enumerate(prompts, start=1):
        text = entry.get("prompt", "")
        print_prompt_status(idx, total, text, "running")

        last = None
        for attempt in range(max_retries + 1):
            if attempt > 0:
                console.print(f"  [yellow]🔄 Retry {attempt}/{max_retries}[/yellow]")
                time.sleep(delay)
            last = run_single_prompt(page, entry, idx, config, selectors)
            if last["status"] == "done":
                break

        print_prompt_status(idx, total, text, last["status"] if last else "failed")
        results.append(last)

        if idx < total:
            time.sleep(delay)

    return results
