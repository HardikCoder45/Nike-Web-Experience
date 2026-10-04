"""Fallback QA: prefers-reduced-motion and a WebGL-less browser."""
import asyncio, json
from playwright.async_api import async_playwright

URL = "http://127.0.0.1:4321/"

async def reduced_motion():
    async with async_playwright() as p:
        br = await p.chromium.launch(channel="chromium",
            args=["--enable-unsafe-swiftshader", "--use-angle=metal"])
        ctx = await br.new_context(viewport={"width": 1440, "height": 900},
                                   reduced_motion="reduce")
        pg = await ctx.new_page()
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        await pg.goto(URL, wait_until="load")
        await pg.wait_for_function(
            "document.getElementById('loader').classList.contains('is-done')", timeout=45000)
        await pg.wait_for_timeout(2500)
        await pg.screenshot(path="/tmp/qa/deg-reduced-hero.png")
        await pg.evaluate("document.querySelector('#anatomy').scrollIntoView({block:'start'})")
        await pg.wait_for_timeout(2000)
        await pg.screenshot(path="/tmp/qa/deg-reduced-anatomy.png")
        st = await pg.evaluate("({reduced: window.phantom ? window.phantom.state() : null,"
                              " tickerX: getComputedStyle(document.querySelector('#ticker')).transform,"
                              " counters: Array.from(document.querySelectorAll('[data-count]')).map(e=>e.textContent),"
                              " tickerAnim: getComputedStyle(document.querySelector('#ticker__row')||document.body).animationName})")
        print("REDUCED MOTION:", json.dumps(st, indent=1))
        print("errors:", errs)
        await br.close()

async def no_webgl():
    async with async_playwright() as p:
        br = await p.chromium.launch(channel="chromium", args=["--use-angle=swiftshader"])
        ctx = await br.new_context(viewport={"width": 1440, "height": 900})
        # kill WebGL2 + WebGL before any page script runs
        await ctx.add_init_script("""
          const kill = (proto) => {
            const d = Object.getOwnPropertyDescriptor(proto, 'getContext');
            Object.defineProperty(proto, 'getContext', {
              configurable: true, value: function (t, o) {
                if (String(t).startsWith('webgl')) return null;
                return d.value.call(this, t, o);
              }});
          };
          kill(HTMLCanvasElement.prototype);
          kill(OffscreenCanvas.prototype);
        """)
        pg = await ctx.new_page()
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        await pg.goto(URL, wait_until="load")
        await pg.wait_for_function(
            "document.getElementById('loader').classList.contains('is-done')", timeout=30000)
        await pg.wait_for_timeout(1500)
        await pg.screenshot(path="/tmp/qa/deg-nowebgl-hero.png")
        await pg.evaluate("document.querySelector('#colorway').scrollIntoView({block:'start'})")
        await pg.wait_for_timeout(900)
        await pg.click('.swatch[data-cw="volt"]')
        await pg.wait_for_timeout(400)
        await pg.screenshot(path="/tmp/qa/deg-nowebgl-buy.png")
        st = await pg.evaluate("""({
          noWebgl: document.body.classList.contains('no-webgl'),
          h1: (document.querySelector('h1')||{}).textContent,
          canvasHidden: getComputedStyle(document.querySelector('.stage-fixed')).display,
          hotspotsHidden: getComputedStyle(document.querySelector('.hotspots')).display,
          price: document.getElementById('mPrice').textContent,
          addWorks: !!document.getElementById('addBtn'),
        })""")
        print("NO WEBGL:", json.dumps(st, indent=1))
        print("errors:", errs)
        await br.close()

asyncio.run(reduced_motion())
asyncio.run(no_webgl())
