"""
inspect_grok2.py — Uses venv playwright to inspect grok.com/imagine

Run with the venv interpreter:
  .venv\Scripts\python.exe inspect_grok2.py
"""
import json, os, sys, time
from playwright.sync_api import sync_playwright

PROFILE = os.path.abspath("./browser_profile")
OUT_DIR = "./inspect_output"
os.makedirs(OUT_DIR, exist_ok=True)

def main():
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=PROFILE,
            headless=False,
            slow_mo=100,
            viewport={"width": 1280, "height": 900},
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()

        print("→ Navigating to grok.com/imagine …")
        page.goto("https://grok.com/imagine", wait_until="domcontentloaded", timeout=30000)
        time.sleep(5)

        # Screenshot
        page.screenshot(path=f"{OUT_DIR}/grok_imagine.png", full_page=False)
        print(f"✅ Screenshot → {OUT_DIR}/grok_imagine.png")

        # Dump ALL buttons with text + attrs
        data = page.evaluate("""() => {
            const info = (el) => {
                const attrs = {};
                for (const a of el.attributes) attrs[a.name] = a.value;
                return {
                    tag: el.tagName,
                    text: el.innerText ? el.innerText.trim().slice(0, 120) : '',
                    attrs: attrs,
                    className: el.className,
                    id: el.id,
                    visible: el.offsetParent !== null,
                    outerHTML: el.outerHTML.slice(0, 300)
                };
            };
            const buttons = [...document.querySelectorAll('button, [role=button], select, option')].map(info);
            const inputs = [...document.querySelectorAll('textarea, input, [contenteditable]')].map(info);
            const allInteractive = [...document.querySelectorAll('[class*=mode],[class*=video],[class*=image],[class*=ratio],[class*=quality],[class*=length],[class*=select],[class*=dropdown],[class*=toggle]')].map(info);
            return { buttons, inputs, allInteractive };
        }""")

        with open(f"{OUT_DIR}/elements.json", "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print(f"✅ Elements JSON → {OUT_DIR}/elements.json")
        print(f"   Buttons: {len(data['buttons'])}")
        print(f"   Inputs:  {len(data['inputs'])}")
        print(f"   Interactive class elements: {len(data['allInteractive'])}")

        # Print a quick summary
        print("\n── BUTTONS ─────────────────────────────────")
        for b in data["buttons"]:
            if b["visible"] and (b["text"] or b["attrs"].get("aria-label")):
                print(f"  [{b['tag']}] text='{b['text'][:60]}' aria='{b['attrs'].get('aria-label','')}' class='{b['className'][:60]}'")

        print("\n── INPUTS ──────────────────────────────────")
        for i in data["inputs"]:
            print(f"  [{i['tag']}] placeholder='{i['attrs'].get('placeholder','')}' ce='{i['attrs'].get('contenteditable','')}' class='{i['className'][:60]}'")

        print("\n── INTERACTIVE CLASS ELEMENTS ──────────────")
        for el in data["allInteractive"][:30]:
            if el["visible"]:
                print(f"  [{el['tag']}] text='{el['text'][:60]}' class='{el['className'][:80]}'")

        print("\nDone. Press Ctrl+C to close browser.")
        try:
            while True: time.sleep(5)
        except KeyboardInterrupt:
            pass
        ctx.close()

if __name__ == "__main__":
    main()
