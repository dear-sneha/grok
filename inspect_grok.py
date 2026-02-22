"""
inspect_grok.py — One-shot Playwright inspector.

Navigates to grok.com/imagine (using saved profile), saves a screenshot,
and dumps all interactive elements so we can identify the correct selectors.
Run once, look at inspect_output/ for results, then Ctrl+C to exit.
"""

import json, os, time
from playwright.sync_api import sync_playwright

PROFILE = os.path.abspath("./browser_profile")
OUT_DIR = "./inspect_output"
os.makedirs(OUT_DIR, exist_ok=True)

with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(
        user_data_dir=PROFILE,
        headless=False,
        slow_mo=80,
        viewport={"width": 1280, "height": 900},
        args=["--disable-blink-features=AutomationControlled"],
    )
    page = ctx.pages[0] if ctx.pages else ctx.new_page()

    print("Navigating to grok.com/imagine …")
    page.goto("https://grok.com/imagine", wait_until="domcontentloaded", timeout=30000)
    time.sleep(4)  # let React settle

    # Screenshot
    page.screenshot(path=f"{OUT_DIR}/grok_imagine.png", full_page=True)
    print(f"Screenshot saved → {OUT_DIR}/grok_imagine.png")

    # Dump all buttons
    buttons = page.query_selector_all("button")
    btn_data = []
    for b in buttons:
        try:
            text      = (b.inner_text() or "").strip()[:80]
            aria      = b.get_attribute("aria-label") or ""
            data_attrs = page.evaluate(
                "el => Object.fromEntries([...el.attributes].map(a=>[a.name,a.value]))", b
            )
            btn_data.append({"text": text, "aria-label": aria, "attrs": data_attrs})
        except Exception:
            continue

    with open(f"{OUT_DIR}/buttons.json", "w", encoding="utf-8") as f:
        json.dump(btn_data, f, indent=2, ensure_ascii=False)
    print(f"Buttons JSON saved → {OUT_DIR}/buttons.json  ({len(btn_data)} buttons)")

    # Dump all inputs / textareas / contenteditables
    inputs = page.query_selector_all("input, textarea, [contenteditable='true']")
    inp_data = []
    for el in inputs:
        try:
            tag   = el.evaluate("el => el.tagName")
            ph    = el.get_attribute("placeholder") or ""
            ce    = el.get_attribute("contenteditable") or ""
            attrs = page.evaluate(
                "el => Object.fromEntries([...el.attributes].map(a=>[a.name,a.value]))", el
            )
            inp_data.append({"tag": tag, "placeholder": ph, "contenteditable": ce, "attrs": attrs})
        except Exception:
            continue

    with open(f"{OUT_DIR}/inputs.json", "w", encoding="utf-8") as f:
        json.dump(inp_data, f, indent=2, ensure_ascii=False)
    print(f"Inputs JSON saved  → {OUT_DIR}/inputs.json   ({len(inp_data)} elements)")

    # Dump full page HTML for deeper analysis
    html = page.content()
    with open(f"{OUT_DIR}/page.html", "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Full HTML saved    → {OUT_DIR}/page.html")

    print("\nInspection complete.  Keeping browser open — press Ctrl+C when done.")
    try:
        while True:
            time.sleep(5)
    except KeyboardInterrupt:
        pass

    ctx.close()
