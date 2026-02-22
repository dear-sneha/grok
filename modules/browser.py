"""
modules/browser.py — Playwright browser setup and fully automated Grok login.

Login flow:
  1. Launch persistent Chromium with saved browser_profile/
  2. Navigate to grok.com/imagine
  3. If already logged in → done
  4. Click "Sign in" → click "Continue with Google"
  5. Auto-fill Google email → click Next
  6. Auto-fill Google password → click Next
  7. Handle "Choose an account" picker if present
  8. Handle 2-step verification prompt (waits for user if needed)
  9. Wait for grok.com to confirm login
  10. Session saved automatically — never asks again
"""

import os
import time

from playwright.sync_api import sync_playwright, Page, BrowserContext, Playwright

from modules.logger import console, print_info, print_success, print_warning, print_error

# ─── Constants ────────────────────────────────────────────────────────────────

GROK_URL          = "https://grok.com"
GROK_IMAGINE_URL  = "https://grok.com/imagine"
BROWSER_PROFILE_DIR = os.path.abspath("./browser_profile")

# Selectors that prove an active Grok session
LOGIN_SUCCESS_SELECTORS = [
    "textarea",
    "[contenteditable='true']",
    "[data-testid*='prompt']",
    "[placeholder*='Ask']",
    "[placeholder*='Describe']",
    "button[aria-label*='Send']",
    "button[aria-label*='send']",
    "main textarea",
]

# Seconds to wait for the whole login flow end-to-end
LOGIN_FLOW_TIMEOUT = 180

# ─── Browser lifecycle ────────────────────────────────────────────────────────

_playwright_instance: Playwright | None = None
_context: BrowserContext | None = None


def create_browser(config: dict) -> Page:
    """
    Launch a persistent Chromium browser using the saved profile directory.
    Returns the first Page ready for navigation.
    """
    global _playwright_instance, _context

    headless: bool = config.get("headless", False)
    os.makedirs(BROWSER_PROFILE_DIR, exist_ok=True)

    print_info(f"Launching browser  (headless={headless}) …")
    print_info(f"Profile directory : {BROWSER_PROFILE_DIR}")

    _playwright_instance = sync_playwright().start()

    _context = _playwright_instance.chromium.launch_persistent_context(
        user_data_dir=BROWSER_PROFILE_DIR,
        headless=headless,
        slow_mo=120,          # slightly slower for reliability
        args=[
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-infobars",
        ],
        ignore_https_errors=True,
        viewport={"width": 1280, "height": 900},
        locale="en-US",
        timezone_id="America/New_York",
    )

    # Stealth patch
    _context.add_init_script(
        "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    )

    pages = _context.pages
    page  = pages[0] if pages else _context.new_page()
    return page


def close_browser():
    """Gracefully shut down browser and Playwright."""
    global _playwright_instance, _context
    for obj in (_context, _playwright_instance):
        if obj:
            try:
                obj.close() if hasattr(obj, "close") else obj.stop()
            except Exception:
                pass


# ─── Login state detection ────────────────────────────────────────────────────

def is_logged_in(page: Page) -> bool:
    """Return True if grok.com shows an active session."""
    try:
        page.wait_for_load_state("domcontentloaded", timeout=10_000)
    except Exception:
        pass
    if "grok.com" not in page.url:
        return False
    for sel in LOGIN_SUCCESS_SELECTORS:
        try:
            elem = page.query_selector(sel)
            if elem and elem.is_visible():
                return True
        except Exception:
            continue
    return False


# ─── Helper: robust click ─────────────────────────────────────────────────────

def _safe_click(page: Page, selector: str, timeout: int = 8000) -> bool:
    """Try each comma-separated part of a compound selector."""
    parts = [s.strip() for s in selector.split(",")]
    for part in parts:
        try:
            page.wait_for_selector(part, state="visible", timeout=timeout // max(len(parts), 1))
            elem = page.query_selector(part)
            if elem and elem.is_visible():
                elem.scroll_into_view_if_needed()
                elem.click()
                return True
        except Exception:
            continue
    return False


def _safe_fill(page: Page, selector: str, value: str, timeout: int = 8000) -> bool:
    """Wait for input, clear it, and type value."""
    parts = [s.strip() for s in selector.split(",")]
    for part in parts:
        try:
            page.wait_for_selector(part, state="visible", timeout=timeout // max(len(parts), 1))
            elem = page.query_selector(part)
            if elem and elem.is_visible():
                elem.click()
                elem.fill("")
                elem.type(value, delay=60)
                return True
        except Exception:
            continue
    return False


# ─── Google OAuth sub-steps ───────────────────────────────────────────────────

def _handle_google_login(page: Page, email: str, password: str):
    """
    Fully automated Google sign-in.  Handles:
      • Account picker ("Choose an account")  — picks matching email or "Use another account"
      • Email entry form
      • Password entry form
      • "Stay signed in?" prompt
      • reCAPTCHA / 2FA — leaves to user if detected
    """

    def _current_url():
        try:
            return page.url
        except Exception:
            return ""

    deadline = time.time() + LOGIN_FLOW_TIMEOUT

    while time.time() < deadline:
        url = _current_url()

        # ── Success: back on grok.com ──────────────────────────────────────
        if "grok.com" in url and is_logged_in(page):
            return

        # ── Account picker ("Choose an account") ──────────────────────────
        if "accounts.google.com" in url:
            page.wait_for_timeout(800)

            # If matching email tile exists, click it
            email_tile_selectors = [
                f"[data-email='{email}']",
                f"[aria-label*='{email}']",
                f"li:has-text('{email}')",
                f"div:has-text('{email}')",
            ]
            clicked_tile = False
            for sel in email_tile_selectors:
                try:
                    elem = page.query_selector(sel)
                    if elem and elem.is_visible():
                        elem.click()
                        print_info(f"Selected account tile: {email}")
                        clicked_tile = True
                        break
                except Exception:
                    continue

            if not clicked_tile:
                # Click "Use another account" if available
                for sel in [
                    "[data-identifier='']",
                    "li:has-text('Use another account')",
                    "div:has-text('Use another account')",
                ]:
                    try:
                        elem = page.query_selector(sel)
                        if elem and elem.is_visible():
                            elem.click()
                            print_info("Clicked 'Use another account'")
                            page.wait_for_timeout(1000)
                            break
                    except Exception:
                        continue

            page.wait_for_timeout(1200)
            continue

        # ── Email entry form ───────────────────────────────────────────────
        if "accounts.google.com" in url or "google.com/signin" in url:
            # Email field
            email_selectors = "input[type='email'], input[name='identifier'], input[name='email']"
            email_visible = False
            for sel in [s.strip() for s in email_selectors.split(",")]:
                try:
                    elem = page.query_selector(sel)
                    if elem and elem.is_visible():
                        email_visible = True
                        break
                except Exception:
                    continue

            if email_visible:
                if _safe_fill(page, email_selectors, email):
                    print_info(f"Filled email: {email}")
                    page.wait_for_timeout(500)
                    # Click Next / Continue
                    next_clicked = _safe_click(
                        page,
                        "#identifierNext, [id='identifierNext'], "
                        "button:has-text('Next'), button:has-text('Continue')",
                        timeout=5000,
                    )
                    if next_clicked:
                        print_info("Clicked Next after email")
                    page.wait_for_timeout(1500)
                    continue

            # Password field
            pwd_selectors = (
                "input[type='password'], "
                "input[name='password'], "
                "input[name='Passwd']"
            )
            pwd_visible = False
            for sel in [s.strip() for s in pwd_selectors.split(",")]:
                try:
                    elem = page.query_selector(sel)
                    if elem and elem.is_visible():
                        pwd_visible = True
                        break
                except Exception:
                    continue

            if pwd_visible:
                if _safe_fill(page, pwd_selectors, password):
                    print_info("Filled password")
                    page.wait_for_timeout(500)
                    # Click Next / Sign in
                    next_clicked = _safe_click(
                        page,
                        "#passwordNext, [id='passwordNext'], "
                        "button:has-text('Next'), button:has-text('Sign in')",
                        timeout=5000,
                    )
                    if next_clicked:
                        print_info("Clicked Next after password")
                    page.wait_for_timeout(2500)
                    continue

            # "Stay signed in?" / confirm prompts
            for confirm_sel in [
                "button:has-text('Yes')",
                "button:has-text('Continue')",
                "button:has-text('I agree')",
                "button:has-text('Allow')",
                "#confirm-btn",
                "[jsname='LgbsSe']",
            ]:
                try:
                    elem = page.query_selector(confirm_sel)
                    if elem and elem.is_visible():
                        elem.click()
                        print_info(f"Clicked confirm button: {confirm_sel}")
                        page.wait_for_timeout(1500)
                        break
                except Exception:
                    continue

        # Small sleep before next poll
        time.sleep(1.5)

    # Timed out inside Google — log a warning but let caller handle it
    print_warning("Google login sub-flow timed out (may need manual 2FA).")


# ─── Main public function ─────────────────────────────────────────────────────

def login_to_grok(page: Page, config: dict | None = None) -> bool:
    """
    Full login flow.  Accepts an optional config dict to pull credentials from.
    Returns True on success, raises RuntimeError on timeout.
    """
    email    = (config or {}).get("grok_email", "")
    password = (config or {}).get("grok_password", "")

    print_info("Navigating to Grok …")
    try:
        page.goto(GROK_IMAGINE_URL, wait_until="domcontentloaded", timeout=30_000)
    except Exception:
        page.goto(GROK_URL, wait_until="domcontentloaded", timeout=30_000)

    page.wait_for_timeout(2000)

    # ── Already logged in? ──────────────────────────────────────────────────
    if is_logged_in(page):
        print_success("Already logged in — session reused from saved profile ✓")
        return True

    print_info("Session not found. Starting automated Google OAuth …")

    # ── Click "Sign in" on grok.com ─────────────────────────────────────────
    sign_in_selectors = (
        "button:has-text('Sign in'), "
        "a:has-text('Sign in'), "
        "button:has-text('Log in'), "
        "a:has-text('Log in'), "
        "[aria-label*='Sign in'], "
        "[data-testid*='signin'], "
        "[href*='login'], "
        "[href*='signin']"
    )
    if _safe_click(page, sign_in_selectors, timeout=10_000):
        print_info("Clicked Sign in button on Grok")
    else:
        print_warning("Sign-in button not auto-found — proceeding anyway")

    page.wait_for_timeout(1500)

    # ── Click "Continue with Google" ────────────────────────────────────────
    google_selectors = (
        "button:has-text('Google'), "
        "a:has-text('Google'), "
        "button:has-text('Continue with Google'), "
        "[aria-label*='Google'], "
        "[data-provider='google'], "
        "[class*='google']"
    )
    if _safe_click(page, google_selectors, timeout=10_000):
        print_info("Clicked 'Continue with Google'")
    else:
        print_warning("Google button not found — may already be on Google login page")

    page.wait_for_timeout(2000)

    # ── Run automated Google sign-in ────────────────────────────────────────
    if email and password:
        print_info(f"Auto-filling credentials for: {email}")
        _handle_google_login(page, email, password)
    else:
        console.print(
            f"\n  [yellow]No credentials in config.json — "
            f"please sign in manually in the browser window.[/yellow]\n"
            f"  [dim]Waiting {LOGIN_FLOW_TIMEOUT}s …[/dim]\n"
        )

    # ── Wait for confirmed login on grok.com ────────────────────────────────
    deadline = time.time() + LOGIN_FLOW_TIMEOUT
    while time.time() < deadline:
        try:
            if "grok.com" in page.url and is_logged_in(page):
                print_success("Login successful! Session saved to browser_profile/ ✓")
                return True
        except Exception:
            pass
        time.sleep(2)

    raise RuntimeError(
        "Login timed out after all automated steps. "
        "If Google sent a 2-step verification code, run the script again "
        "and approve it in the browser window before the timeout."
    )
