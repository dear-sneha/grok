"""
inspect_dropdown.py — Click the model trigger, dump what appears in the dropdown.
Run: .venv\Scripts\python.exe inspect_dropdown.py
"""
import json, os, time
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

        print("Navigating to grok.com/imagine …")
        page.goto("https://grok.com/imagine", wait_until="domcontentloaded", timeout=30000)
        time.sleep(4)

        # Click the model select trigger
        trigger = page.query_selector("#model-select-trigger")
        if trigger:
            print(f"Found trigger: {trigger.inner_text()!r}")
            trigger.click()
            time.sleep(1.5)  # wait for dropdown animation
        else:
            print("Trigger NOT found!")

        # Screenshot after clicking
        page.screenshot(path=f"{OUT_DIR}/after_trigger_click.png")
        print(f"Screenshot saved")

        # Dump all elements that appeared (in any portal/overlay)
        dropdown_data = page.evaluate("""() => {
            const info = el => ({
                tag: el.tagName,
                role: el.getAttribute('role'),
                text: (el.innerText || '').trim().slice(0, 100),
                attrs: Object.fromEntries([...el.attributes].map(a => [a.name, a.value])),
                outerHTML: el.outerHTML.slice(0, 400),
                visible: el.offsetParent !== null,
                rect: el.getBoundingClientRect()
            });

            // Look for Radix dropdown portals
            const portals = document.querySelectorAll('[data-radix-popper-content-wrapper], [data-radix-portal], [role=menu], [role=listbox], [role=dialog]');
            const menuItems = document.querySelectorAll('[role=menuitem], [role=option], [role=menuitemradio], [role=menuitemcheckbox]');
            const allVisible = [...document.querySelectorAll('*')].filter(el => {
                const r = el.getBoundingClientRect();
                return r.width > 0 && r.height > 0 && r.top > 0 && r.top < window.innerHeight;
            });

            return {
                portals: [...portals].map(info),
                menuItems: [...menuItems].map(info),
                // All text-containing elements visible in viewport that appeared after click (check for Video/Image text)
                videoImgItems: [...document.querySelectorAll('*')].filter(el => {
                    const t = (el.innerText || '').trim();
                    return (t === 'Video' || t === 'Image' || t === 'Aurora' || t.includes('Aurora') || t.includes('Video') && t.length < 30) &&
                           el.getBoundingClientRect().width > 0;
                }).slice(0, 30).map(info)
            };
        }""")

        with open(f"{OUT_DIR}/dropdown.json", "w", encoding="utf-8") as f:
            json.dump(dropdown_data, f, indent=2, ensure_ascii=False)

        print(f"\nPortals found: {len(dropdown_data['portals'])}")
        print(f"Menu items found: {len(dropdown_data['menuItems'])}")
        print(f"Video/Image items: {len(dropdown_data['videoImgItems'])}")

        print("\n── PORTALS ───────────────────────────────")
        for el in dropdown_data["portals"]:
            print(f"  [{el['tag']}] role={el['role']} text={el['text'][:60]!r}")

        print("\n── MENU ITEMS ────────────────────────────")
        for el in dropdown_data["menuItems"]:
            print(f"  [{el['tag']}] role={el['role']} text={el['text'][:80]!r}")
            print(f"    attrs: {el['attrs']}")

        print("\n── VIDEO/IMAGE ELEMENTS ──────────────────")
        for el in dropdown_data["videoImgItems"]:
            print(f"  [{el['tag']}] role={el['role']} text={el['text']!r}")
            print(f"    class: {el['attrs'].get('class','')[:80]}")
            print(f"    outerHTML: {el['outerHTML'][:200]}")

        print("\nKeeping browser open — press Ctrl+C when done.")
        try:
            while True: time.sleep(5)
        except KeyboardInterrupt:
            pass
        ctx.close()

if __name__ == "__main__":
    main()
