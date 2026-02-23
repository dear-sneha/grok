#!/usr/bin/env python3
"""
grok_auto.py — Grok Automation Standalone Script
=================================================
Runs anywhere on Windows / Mac / Linux. No browser extension required.
Uses a persistent Playwright Chromium session — login only once.

Usage:
  python grok_auto.py                            # Uses config.json + prompts.json
  python grok_auto.py --prompt "A sunset sky"    # Single prompt via CLI
  python grok_auto.py --mode textToImage         # Override mode from config
  python grok_auto.py --headless                 # Run without visible browser
  python grok_auto.py --upload-drive             # Upload to Google Drive after generation
  python grok_auto.py --upload-youtube           # Upload to YouTube after generation
  python grok_auto.py --config my_config.json    # Use a custom config file
  python grok_auto.py --prompts my_prompts.json  # Use a custom prompts file

Setup (first time):
  pip install -r requirements.txt
  playwright install chromium
"""

import argparse
import json
import os
import sys
import time

# ─── Dependency check ─────────────────────────────────────────────────────────

def _check_dependencies():
    missing = []
    for pkg, import_name in [
        ("playwright", "playwright"),
        ("httpx", "httpx"),
        ("rich", "rich"),
    ]:
        try:
            __import__(import_name)
        except ImportError:
            missing.append(pkg)
    if missing:
        print(f"ERROR: Missing Python packages: {', '.join(missing)}")
        print(f"Run:  pip install -r requirements.txt")
        sys.exit(1)

_check_dependencies()

# ─── Imports (after dep check) ────────────────────────────────────────────────

from modules.logger import (
    console,
    print_header,
    print_section,
    print_info,
    print_success,
    print_warning,
    print_error,
    print_summary,
)
from modules.browser import create_browser, login_to_grok, close_browser
from modules.grok_ui import run_automation

# ─── Defaults ─────────────────────────────────────────────────────────────────

DEFAULT_CONFIG_FILE = "config.json"
DEFAULT_PROMPTS_FILE = "prompts.json"

DEFAULT_CONFIG = {
    "grok_email": "",
    "mode": "textToVideo",
    "aspect_ratio": "9:16",
    "video_length": "6s",
    "video_quality": "720p",
    "output_count": 1,
    "concurrent_prompts": 1,
    "prompt_delay_seconds": 3,
    "max_retries": 3,
    "generation_timeout_seconds": 360,
    "output_folder": "./output",
    # Google Drive
    "auto_upload_drive": False,
    "drive_folder": "",          # empty = auto "Grok-DD-MM-YYYY"
    "drive_parent_id": "",       # optional parent folder ID
    "drive_make_public": False,  # share link with anyone
    # YouTube
    "auto_upload_youtube": False,
    "youtube_privacy": "private",
    "youtube_description": "Generated with Grok Automation.",
    "youtube_tags": ["AI", "Grok", "automation"],
    # Direct upload (skip local save)
    "no_local_save": False,   # True = stream media bytes straight to Drive, nothing written locally
    "headless": False,
}

# ─── Config loading ───────────────────────────────────────────────────────────

def load_config(config_path: str) -> dict:
    """Load config.json and merge with defaults."""
    if not os.path.exists(config_path):
        print_warning(
            f"'{config_path}' not found — using built-in defaults. "
            f"Create '{DEFAULT_CONFIG_FILE}' to customise settings."
        )
        return dict(DEFAULT_CONFIG)

    with open(config_path, "r", encoding="utf-8") as f:
        user_config = json.load(f)

    merged = {**DEFAULT_CONFIG, **user_config}
    print_success(f"Config loaded from: {config_path}")
    return merged


def load_prompts(prompts_path: str) -> list:
    """Load prompts.json and return the list."""
    if not os.path.exists(prompts_path):
        print_error(
            f"'{prompts_path}' not found. "
            "Create the file or pass a prompt with --prompt."
        )
        sys.exit(1)

    with open(prompts_path, "r", encoding="utf-8") as f:
        prompts = json.load(f)

    if not isinstance(prompts, list) or not prompts:
        print_error(f"'{prompts_path}' must be a non-empty JSON array.")
        sys.exit(1)

    print_success(f"Loaded {len(prompts)} prompt(s) from: {prompts_path}")
    return prompts

# ─── Argument parsing ─────────────────────────────────────────────────────────

def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="grok_auto",
        description="Grok Automation — Standalone batch generator for grok.com",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python grok_auto.py\n"
            "  python grok_auto.py --prompt 'A futuristic city at sunset'\n"
            "  python grok_auto.py --mode textToImage --headless\n"
            "  python grok_auto.py --upload-drive --upload-youtube\n"
        ),
    )
    parser.add_argument("--prompt", type=str, help="Single prompt (overrides prompts.json)")
    parser.add_argument(
        "--mode",
        type=str,
        choices=["textToVideo", "imageToVideo", "componentsToVideo", "textToImage", "imageToImage"],
        help="Generation mode (overrides config.json)",
    )
    parser.add_argument("--headless", action="store_true", help="Run browser in headless mode")
    parser.add_argument("--upload-drive", action="store_true", help="Upload outputs to Google Drive")
    parser.add_argument("--upload-youtube", action="store_true", help="Upload MP4s to YouTube")
    parser.add_argument(
        "--drive-folder",
        type=str,
        default=None,
        help="Google Drive folder name to upload into (e.g. 'Grok-Feb2026'). Defaults to 'Grok-DD-MM-YYYY'.",
    )
    parser.add_argument(
        "--no-local-save",
        action="store_true",
        help="Skip saving to disk — stream generated media directly to Google Drive (requires --upload-drive)",
    )
    parser.add_argument(
        "--auth-drive",
        action="store_true",
        help="Test Google Drive OAuth (opens browser for auth if needed) then exit",
    )
    parser.add_argument("--config", type=str, default=DEFAULT_CONFIG_FILE, help="Path to config JSON")
    parser.add_argument("--prompts", type=str, default=DEFAULT_PROMPTS_FILE, help="Path to prompts JSON")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show settings and prompts then exit (no browser launched)",
    )
    return parser

# ─── Dry-run display ──────────────────────────────────────────────────────────

def dry_run(config: dict, prompts: list):
    """Print resolved settings and prompt list, then exit."""
    from rich.table import Table
    from rich import box

    print_section("Dry Run — Resolved Configuration")
    cfg_table = Table(show_header=True, header_style="bold cyan", box=box.SIMPLE)
    cfg_table.add_column("Setting", style="cyan")
    cfg_table.add_column("Value", style="white")
    for k, v in config.items():
        cfg_table.add_row(k, str(v))
    console.print(cfg_table)

    print_section("Prompts")
    for i, p in enumerate(prompts, 1):
        console.print(f"  [bold]{i}.[/bold] {p.get('prompt', '???')[:80]}")
    console.print()
    print_info("Dry run complete — no browser was launched.")

# ─── Upload helpers ───────────────────────────────────────────────────────────

def handle_uploads(file_paths: list[str], config: dict):
    """Run Drive and/or YouTube uploads if configured."""
    if not file_paths:
        print_warning("No files to upload.")
        return

    if config.get("auto_upload_drive"):
        print_section("Google Drive Upload")
        try:
            from modules.drive_upload import upload_to_drive
            upload_to_drive(file_paths, config)
        except Exception as exc:
            print_error(f"Drive upload error: {exc}")

    if config.get("auto_upload_youtube"):
        print_section("YouTube Upload")
        try:
            from modules.youtube_upload import upload_to_youtube
            upload_to_youtube(file_paths, config)
        except Exception as exc:
            print_error(f"YouTube upload error: {exc}")

# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    print_header()

    parser = build_arg_parser()
    args = parser.parse_args()

    # Load config
    config = load_config(args.config)

    # Apply CLI overrides
    if args.mode:
        config["mode"] = args.mode
    if args.headless:
        config["headless"] = True
    if args.upload_drive:
        config["auto_upload_drive"] = True
    if args.upload_youtube:
        config["auto_upload_youtube"] = True
    if args.no_local_save:
        config["no_local_save"] = True
        # no_local_save only works with Drive; auto-enable it
        config["auto_upload_drive"] = True
    if args.drive_folder:
        config["drive_folder"] = args.drive_folder

    # ── Drive auth test ───────────────────────────────────────────────────
    if args.auth_drive:
        from modules.drive_upload import setup_drive_auth
        ok = setup_drive_auth()
        sys.exit(0 if ok else 1)

    # Build prompt list
    if args.prompt:
        prompts = [{"prompt": args.prompt, "images": [], "isConcat": False}]
        print_success(f"Single prompt mode: '{args.prompt[:70]}'")
    else:
        prompts = load_prompts(args.prompts)

    # Dry run?
    if args.dry_run:
        dry_run(config, prompts)
        return

    # ── Display run summary ────────────────────────────────────────────────
    print_section("Run Configuration")
    print_info(f"Mode          : {config['mode']}")
    print_info(f"Prompts       : {len(prompts)}")
    print_info(f"Aspect ratio  : {config['aspect_ratio']}")
    print_info(f"Output folder : {'(skipped — direct Drive upload)' if config.get('no_local_save') else config['output_folder']}")
    print_info(f"Drive upload  : {'direct (no local save)' if config.get('no_local_save') else config.get('auto_upload_drive', False)}")
    print_info(f"Headless      : {config['headless']}")
    print_info(f"Max retries   : {config['max_retries']}")
    console.print()

    page = None
    try:
        # ── Launch browser ─────────────────────────────────────────────────
        print_section("Browser Launch")
        page = create_browser(config)

        # ── Login ──────────────────────────────────────────────────────────
        print_section("Authentication")
        login_to_grok(page, config)
        console.print()

        # ── Run batch generation ───────────────────────────────────────────
        print_section("Generation")
        start_time = time.time()
        results = run_automation(page, prompts, config)
        elapsed = round(time.time() - start_time, 1)
        print_info(f"Batch completed in {elapsed}s")

        # ── Collect downloaded files ───────────────────────────────────────
        all_files = [f for r in results for f in r.get("saved_files", [])]

        # ── End-of-batch uploads ───────────────────────────────────────────
        # Drive: already uploaded per-prompt inside grok_ui (no_local_save or normal mode).
        # YouTube: still batched here since it needs local files.
        if not config.get("no_local_save") and all_files and config.get("auto_upload_youtube"):
            print_section("YouTube Upload")
            try:
                from modules.youtube_upload import upload_to_youtube
                upload_to_youtube(all_files, config)
            except Exception as exc:
                print_error(f"YouTube upload error: {exc}")


        # ── Summary ───────────────────────────────────────────────────────
        print_summary(results)

    except KeyboardInterrupt:
        print_warning("Interrupted by user (Ctrl+C). Shutting down …")
    except Exception as exc:
        print_error(f"Fatal error: {exc}")
        import traceback
        console.print_exception()
        sys.exit(1)
    finally:
        if page:
            try:
                close_browser()
            except Exception:
                pass


if __name__ == "__main__":
    main()
