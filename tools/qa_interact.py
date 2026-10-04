import asyncio, json, sys
from playwright.async_api import async_playwright

URL = "http://127.0.0.1:4321/"

async def main():
    async with async_playwright() as p:
        br = await p.chromium.launch(channel="chromium", args=[
            "--enable-gpu", "--ignore-gpu-blocklist", "--enable-unsafe-swiftshader", "--use-angle=metal"])
        ctx = await br.new_context(viewport={"width": 1440, "height": 900})
        pg = await ctx.new_page()
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.on("console", lambda m: errs.append(f"[{m.type}] {m.text}") if m.type == "error" else None)
        await pg.goto(URL, wait_until="load")
        await pg.wait_for_function("document.getElementById('loader').classList.contains('is-done')", timeout=45000)
        await pg.wait_for_timeout(2500)

        res = {}
        # --- colorway switching drives the real material --------------------
        await pg.evaluate("document.querySelector('#colorway').scrollIntoView({block:'start'})")
        await pg.wait_for_timeout(1800)
        before = await pg.evaluate("window.phantom.upperHex()")
        for cw in ("volt", "infrared", "glacier", "bone"):
            await pg.click(f'.swatch[data-cw="{cw}"]')
            await pg.wait_for_timeout(700)
            res[cw] = await pg.evaluate("({mat:window.phantom.upperHex(), name:document.getElementById('mName').textContent, price:document.getElementById('mPrice').textContent})")
        await pg.screenshot(path="/tmp/qa/int-colorway.png")

        # --- size + add to bag ---------------------------------------------
        await pg.click('.size[data-s="10"]')
        await pg.click("#addBtn")
        await pg.wait_for_timeout(700)
        res['cartOpen'] = await pg.evaluate("document.getElementById('cart').classList.contains('is-open')")
        res['cartCount'] = await pg.evaluate("document.getElementById('cartCount').textContent")
        res['cartTotal'] = await pg.evaluate("document.getElementById('cartTotal').textContent")
        await pg.screenshot(path="/tmp/qa/int-cart.png")
        await pg.keyboard.press("Escape")
        await pg.wait_for_timeout(600)
        res['cartClosedByEsc'] = not await pg.evaluate("document.getElementById('cart').classList.contains('is-open')")

        # --- explode toggle -------------------------------------------------
        await pg.evaluate("document.querySelector('#anatomy').scrollIntoView({block:'start'})")
        await pg.wait_for_timeout(1500)
        await pg.click("#explodeToggle")
        await pg.wait_for_timeout(1400)
        res['explodeAfterToggle'] = await pg.evaluate("window.phantom.explode()")
        res['toggleLabel'] = await pg.evaluate("document.getElementById('explodeToggle').textContent.trim()")
        await pg.screenshot(path="/tmp/qa/int-explode.png")

        # --- drag to orbit (tested on the hero, where the canvas is the target)
        await pg.evaluate("window.scrollTo(0,0)")
        await pg.wait_for_timeout(1600)
        spin0 = await pg.evaluate("window.phantom.spin()")
        await pg.mouse.move(1150, 500)
        await pg.mouse.down()
        for i in range(14):
            await pg.mouse.move(1150 + i * 24, 500)
            await pg.wait_for_timeout(16)
        await pg.mouse.up()
        await pg.wait_for_timeout(500)
        spin1 = await pg.evaluate("window.phantom.spin()")
        res['spin'] = [round(spin0, 3), round(spin1, 3)]
        res['spinDelta'] = round(spin1 - spin0, 3)
        await pg.screenshot(path="/tmp/qa/int-drag.png")

        # --- links must still be clickable while the canvas is over them ----
        res['navLinkWorks'] = await pg.evaluate("!!document.querySelector('.nav__links a[href=\"#tech\"]')")

        # --- keyboard reachability of every control --------------------------
        await pg.evaluate("window.scrollTo(0,0)")
        await pg.wait_for_timeout(400)
        await pg.keyboard.press("Tab"); await pg.keyboard.press("Tab")
        order = []
        for _ in range(16):
            order.append(await pg.evaluate("document.activeElement.textContent.trim().slice(0,22) || document.activeElement.id || document.activeElement.tagName"))
            await pg.keyboard.press("Tab")
        res['tabOrder'] = order

        # --- newsletter validation ------------------------------------------
        await pg.evaluate("document.querySelector('.foot').scrollIntoView({block:'end'})")
        await pg.fill("#email", "not-an-email")
        await pg.click('#subForm button[type="submit"]')
        await pg.wait_for_timeout(300)
        res['invalidMsg'] = await pg.evaluate("document.getElementById('subMsg').textContent")
        await pg.fill("#email", "runner@example.com")
        await pg.click('#subForm button[type="submit"]')
        await pg.wait_for_timeout(300)
        res['validMsg'] = await pg.evaluate("document.getElementById('subMsg').textContent")

        print(json.dumps({"before": before, **res, "errors": errs}, indent=1))
        await br.close()

asyncio.run(main())
