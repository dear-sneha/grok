#!/usr/bin/env python3
"""
grok_auto.py — Grok Automation Standalone Script
=================================================
Runs anywhere on Windows / Mac / Linux.
No browser extension required.
Uses a persistent Playwright Chromium session — login only once.

Usage:
  python grok_auto.py
  python grok_auto.py --prompt "A sunset sky"
  python grok_auto.py --mode textToImage
  python grok_auto.py --headless
  python grok_auto.py --upload-drive
  python grok_auto.py --upload-youtube
  python grok_auto.py --drive-folder "My Folder"
  python grok_auto.py --auth-drive
  python grok_auto.py --dry-run

Setup (first time):
  pip install -r requirements.txt
  playwright install chromium
"""

import argparse
import json
import os
import sys
import time

# ──────────────────────────────────────────────────────────────────────────────
# Dependency check
# ──────────────────────────────────────────────────────────────────────────────

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
        print("Run: pip install -r requirements.txt")
        sys.exit(1)

_check_dependencies()

# ──────────────────────────────────────────────────────────────────────────────
# Imports
# ──────────────────────────────────────────────────────────────────────────────

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

# ──────────────────────────────────────────────────────────────────────────────
# Defaults
# ──────────────────────────────────────────────────────────────────────────────

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
    "drive_parent_id": "",
    "drive_make_public": False,

    # YouTube
    "auto_upload_youtube": False,
    "youtube_privacy": "private",
    "youtube_description": "Generated with Grok Automation.",
    "youtube_tags": ["AI", "Grok", "automation"],

    # Direct upload
    "no_local_save": False,

    # Browser
    "headless": False,
}

# ──────────────────────────────────────────────────────────────────────────────
# Config loading
# ──────────────────────────────────────────────────────────────────────────────

def load_config(config_path: str) -> dict:
    if not os.path.exists(config_path):
        print_warning(
            f"'{config_path}' not found — using built-in defaults."
        )
        return dict(DEFAULT_CONFIG)

    with open(config_path, "r", encoding="utf-8") as f:
        user_config = json.load(f)

    merged = {**DEFAULT_CONFIG, **user_config}
    print_success(f"Config loaded from: {config_path}")
    return merged


def load_prompts(prompts_path: str) -> list:
    if not os.path.exists(prompts_path):
        print_error(f"'{prompts_path}' not found.")
        sys.exit(1)

    with open(prompts_path, "r", encoding="utf-8") as f:
        prompts = json.load(f)

    if not isinstance(prompts, list) or not prompts:
        print_error(f"'{prompts_path}' must be a non-empty JSON array.")
        sys.exit(1)

    print_success(f"Loaded {len(prompts)} prompt(s) from: {prompts_path}")
    return prompts

# ──────────────────────────────────────────────────────────────────────────────
# Argument parsing
# ──────────────────────────────────────────────────────────────────────────────

def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="grok_auto",
        description="Grok Automation — Standalone batch generator for grok.com",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument("--prompt", type=str, help="Single prompt (overrides prompts.json)")
    parser.add_argument(
        "--mode",
        type=str,
        choices=["textToVideo", "imageToVideo", "componentsToVideo", "textToImage", "imageToImage"],
        help="Generation mode override",
    )

    parser.add_argument("--headless", action="store_true", help="Run browser headless")
    parser.add_argument("--upload-drive", action="store_true", help="Upload to Google Drive")
    parser.add_argument("--upload-youtube", action="store_true", help="Upload to YouTube")

    parser.add_argument(
        "--no-local-save",
        action="store_true",
        help="Skip saving to disk — stream directly to Drive",
    )

    parser.add_argument(
        "--drive-folder",
        type=str,
        default=None,
        help="Override Drive folder name",
    )

    parser.add_argument(
        "--auth-drive",
        action="store_true",
        help="Test Google Drive OAuth then exit",
    )

    parser.add_argument("--config", type=str, default=DEFAULT_CONFIG_FILE)
    parser.add_argument("--prompts", type=str, default=DEFAULT_PROMPTS_FILE)

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show resolved config + prompts then exit",
    )

    return parser

# ──────────────────────────────────────────────────────────────────────────────
# Dry Run
# ──────────────────────────────────────────────────────────────────────────────

def dry_run(config: dict, prompts: list):
    from rich.table import Table
    from rich import box

    print_section("Dry Run — Resolved Configuration")

    table = Table(show_header=True, header_style="bold cyan", box=box.SIMPLE)
    table.add_column("Setting", style="cyan")
    table.add_column("Value", style="white")

    for k, v in config.items():
        table.add_row(k, str(v))

    console.print(table)

    print_section("Prompts")
    for i, p in enumerate(prompts, 1):
        console.print(f"[bold]{i}.[/bold] {p.get('prompt','')[:80]}")

    print_info("Dry run complete — no browser launched.")

# ──────────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────────

def main():
    print_header()

    parser = build_arg_parser()
    args = parser.parse_args()

    config = load_config(args.config)

    # CLI overrides
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
        config["auto_upload_drive"] = True

    if args.drive_folder is not None:
        config["drive_folder"] = args.drive_folder
        print_info(f"Drive folder overridden: {args.drive_folder}")

    # Drive auth test
    if args.auth_drive:
        from modules.drive_upload import setup_drive_auth
        ok = setup_drive_auth()
        sys.exit(0 if ok else 1)

    # Prompt selection
    if args.prompt:
        prompts = [{"prompt": args.prompt, "images": [], "isConcat": False}]
        print_success("Single prompt mode enabled.")
    else:
        prompts = load_prompts(args.prompts)

    if args.dry_run:
        dry_run(config, prompts)
        return

    # ──────────────────────────────────────────────────────────────────
    # Run
    # ──────────────────────────────────────────────────────────────────

    print_section("Run Configuration")
    print_info(f"Mode        : {config['mode']}")
    print_info(f"Prompts     : {len(prompts)}")
    print_info(f"Headless    : {config['headless']}")
    print_info(f"Drive Upload: {config['auto_upload_drive']}")
    print_info(f"YouTube     : {config['auto_upload_youtube']}")
    print_info(f"No Local    : {config['no_local_save']}")
    console.print()

    page = None

    try:
        print_section("Browser Launch")
        page = create_browser(config)

        print_section("Authentication")
        login_to_grok(page, config)

        print_section("Generation")
        start = time.time()
        results = run_automation(page, prompts, config)
        elapsed = round(time.time() - start, 1)

        print_info(f"Completed in {elapsed}s")
        print_summary(results)

    except KeyboardInterrupt:
        print_warning("Interrupted by user.")
    except Exception as exc:
        print_error(f"Fatal error: {exc}")
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