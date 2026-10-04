import asyncio, sys, json
from playwright.async_api import async_playwright

URL = "http://127.0.0.1:4321/"
OUT = "/tmp/qa"

VIEWPORTS = {
    "desktop": (1440, 900),
    "wide":    (1920, 1080),
    "mobile":  (390, 844),
}

async def run(name, w, h, shots, reduced=False):
    async with async_playwright() as p:
        br = await p.chromium.launch(channel="chromium", args=[
            "--enable-gpu", "--ignore-gpu-blocklist", "--enable-unsafe-swiftshader",
            "--enable-webgl", "--use-angle=metal"])
        ctx = await br.new_context(viewport={"width": w, "height": h},
                                   device_scale_factor=2 if w < 500 else 1,
                                   reduced_motion="reduce" if reduced else "no-preference")
        pg = await ctx.new_page()
        # deterministic scrolling: CSS smooth-scroll makes scroll-position
        # assertions race the animation
        await pg.add_init_script(
            "document.addEventListener('DOMContentLoaded',()=>{"
            "document.documentElement.style.scrollBehavior='auto';});")
        logs, errors, failed = [], [], []
        pg.on("console", lambda m: logs.append(f"[{m.type}] {m.text}"))
        pg.on("pageerror", lambda e: errors.append(str(e)))
        pg.on("requestfailed", lambda r: failed.append(f"{r.url} :: {r.failure}"))
        await pg.goto(URL, wait_until="load", timeout=60000)

        # wait for the loader to clear (3D ready) or fail-safe
        try:
            await pg.wait_for_function(
                "document.getElementById('loader').classList.contains('is-done')", timeout=45000)
        except Exception:
            errors.append("loader never completed")

        await pg.wait_for_timeout(3500)
        for label, sel, extra in shots:
            if sel:
                if extra == "bottom":
                    await pg.evaluate("s => document.querySelector(s).scrollIntoView({block:'end'})", sel)
                else:
                    await pg.evaluate("s => document.querySelector(s).scrollIntoView({block:'start'})", sel)
                await pg.wait_for_timeout(2600)
            await pg.screenshot(path=f"{OUT}/{name}-{label}.png")
            d = await pg.evaluate("window.phantom ? window.phantom.state() : null")
            with open(f"{OUT}/dbg-{name}-{label}.json", "w") as fh:
                json.dump(d, fh, indent=1)
            print("shot", f"{name}-{label}", "slot", d["slot"], "run", d["running"],
                  "explode", d["explode"], "fps", d["fps"], "ndcX", d["ndcX"])

        stats = await pg.evaluate("""() => {
          const c = document.getElementById('stage');
          const gl = c && (c.getContext('webgl2') || c.getContext('webgl'));
          return {
            canvas: c ? [c.width, c.height, getComputedStyle(c).position] : null,
            hasGL: !!gl,
            noWebgl: document.body.classList.contains('no-webgl'),
            perf: (document.getElementById('perf')||{}).textContent,
            hotspots: (() => {
              const bar = document.querySelector('.anatomy__bar').getBoundingClientRect();
              return Array.from(document.querySelectorAll('.hotspot')).map((e) => {
                const r = e.getBoundingClientRect();
                const overlaps = e.style.visibility === 'visible'
                  && r.bottom > bar.top && r.top < bar.bottom;
                return (e.dataset.part || '?') + ':' + (e.style.visibility || '-')
                     + (overlaps ? ' BAR-COLLISION' : '');
              });
            })(),
            partCount: ((window.phantom&&window.phantom.parts)||[]).length,
            shoeBox: (window.phantom&&window.phantom.size)||null,
            dbg: window.phantom ? window.phantom.state() : null,
            loaderDone: document.getElementById('loader').classList.contains('is-done'),
            scrollH: document.body.scrollHeight,
            overflowX: document.documentElement.scrollWidth > window.innerWidth,
          };
        }""")
        print(json.dumps({"vp": name, "stats": stats}, indent=1))
        bad = [l for l in logs if l.startswith("[error]") or l.startswith("[warning]")]
        print("CONSOLE ERRORS/WARNINGS:", json.dumps(errors + bad, indent=1) if (errors or bad) else "none")
        print("FAILED REQUESTS:", failed if failed else "none")
        await br.close()

async def main():
    import os
    os.makedirs(OUT, exist_ok=True)
    base = [("hero", None, None),
            ("anatomy", "#anatomy", "start"),
            ("anatomy-end", "#anatomy", "bottom"),
            ("tech", "#tech", "start"),
            ("buy", "#colorway", "start"),
            ("story", "#story", "start"),
            ("foot", ".foot", "bottom")]
    which = sys.argv[1] if len(sys.argv) > 1 else "desktop"
    w, h = VIEWPORTS[which]
    await run(which, w, h, base)

asyncio.run(main())