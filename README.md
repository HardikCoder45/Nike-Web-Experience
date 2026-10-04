# NIKE Air Max Phantom — 3D brand site

A single-page, zero-build brand site in plain HTML, CSS and JavaScript. One WebGL
stage sits behind the whole document and a scroll-scrubbed camera flies it through
five named shots while the product rotates, explodes into an annotated technical
diagram, and re-assembles into a live colorway configurator.

No framework, no bundler, no CDN. `index.html` + `styles.css` + three ES modules
in `js/`, everything else served from `assets/`.

---

## Run it

```bash
cd nikeshoes
python3 -m http.server 4321 --bind 127.0.0.1
# → http://127.0.0.1:4321
```

Any static server works. It must be served over HTTP (ES modules + `fetch` for the
GLB will not load from `file://`).

---

## The concept

**“Engineered to disappear.”** A flagship Air Max is presented as an object under
studio light rather than a photo of a shoe. The scroll is a camera move: the
product arrives as a hero, turns side-on, comes apart into six labelled layers,
pushes away behind the editorial type, then returns as a configurable product.

Five camera shots, each owning one slot of a state object:

| shot | when | what it does |
| --- | --- | --- |
| `hero` | top of page | 3/4 from the toe, pushed into the copy-free right half |
| `dissect` | anatomy | dead side-on, light rings dimmed, exploded by scroll |
| `buy` | configurator | mirrored flank, fully re-assembled, panel scrim on the right |
| `far` | story | small and high, behind the outlined display type |
| `hero` | footer | returns as you scroll back up |

`pickSlot()` chooses the active shot from cached section offsets, and GSAP only
ever scrubs one slot at a time — overlapping scrub tweens on a shared object
fight each other and leave the camera stranded mid-tween.

---

## Files

```
index.html              semantic document: nav, hero, anatomy, tech, buy, story, footer
styles.css              design tokens, layout, responsive, reduced-motion, print
js/main.js              boot, scroll choreography, hotspots, all UI (nav/cart/configurator)
js/stage.js             renderer, environment, lights, atmosphere, post-processing, loop
js/shoe.js              GLB load, part registry, colorways, explode rig
assets/
  models/phantom-runner.glb
  vendor/three/         Three.js r186 build + the six addons actually used
  vendor/gsap/          GSAP + ScrollTrigger
  fonts/                Archivo, Inter, JetBrains Mono (latin subsets, self-hosted)
tools/                  build + QA scripts, not shipped
```

`assets/vendor` and `assets/fonts` are vendored on purpose. The site has zero
runtime third-party requests, so it works offline and cannot break because a CDN
moved a file.

---

## The model

`phantom-runner.glb` is **generated**, not downloaded. `tools/gen_sneaker.py`
builds an original running shoe from lofted cross-sections inside Blender:

- Cross-sections are superellipses with independent top/bottom exponents, so one
  profile gives a flat sole and a domed upper. Points are resampled by arc length,
  which is what keeps smooth shading clean on a low-density loft.
- Every silhouette (`GROUND`, `MID_TOP`, `UPPER_TOP`, `HALF_OUT`, `HALF_UP`) is a
  monotone cubic spline. A monotone interpolator matters here — a Catmull-Rom
  overshoot puts the sole through the floor between control points.
- The collar opening, throat and midsole air window are boolean cuts. The cut
  objects carry the *lining* material and the modifier runs with
  `material_mode='TRANSFER'`, so the new interior walls get shaded as lining
  rather than as more outer knit.
- The heel clip and toe cap are inflated shells trimmed by a half-space boolean.
  Dropping faces one at a time to make a diagonal edge quantised it into a visible
  staircase; the boolean gives one straight cut.
- Knit, tongue, lace and foam normal maps are generated procedurally with numpy
  (tileable value noise + a Sobel height→normal pass) and written as PNGs.

Rebuild everything:

```bash
./tools/build.sh          # add --preview to render studio QA stills to /tmp
```

`build.sh` runs the optimizer with `--palette false`. This is not optional:
`gltf-transform optimize` runs a `palette` transform that **renames materials**
(`MAT_Upper` → `PaletteMaterial003`), and both the colorway switcher and the
exploded view key off those exact names. `tools/gltf/check.cjs` asserts the names
survived and the build fails loudly if they do not.

---

## Interaction

- **Drag anywhere** (that isn't a control) to orbit. Pointer events are bound to
  `window` and the canvas is `pointer-events: none`, so the WebGL layer never
  steals a click from a link or a swatch.
- **← / →** orbit from the keyboard.
- **Colorway swatches** interpolate every material role from its current colour to
  the new one over ~0.4 s. One click lands exactly on the target — the first
  version stepped 16 % per click and never arrived.
- **Explode** is scroll-driven, with a button to pin it.
- **Hotspots** are real 3D anchors projected to screen each frame, hung on fixed
  screen-space leaders so they read as a diagram instead of a shifting stack. Two
  coordinate-space traps live here, both guarded by `tools/qa.py`:
  the labels are absolutely positioned *inside* `.anatomy__viewport`, so window-space
  anchors need the container's origin subtracted back out; and the scrubber's
  position is measured from the DOM rather than hardcoded. The QA asserts no label
  rect ever overlaps `.anatomy__bar`.
- **Bag**, **size grid** and **newsletter** all work.

---

## Quality tiers

`pickTier()` picks from `deviceMemory`, `hardwareConcurrency` and pointer type.

| tier | DPR cap | bloom | dust | used when |
| --- | --- | --- | --- | --- |
| high | 1.75 | yes | 1400 | desktop, ≥8 GB, >4 cores |
| medium | 1.35 | yes | 700 | ≤4 GB or ≤4 cores |
| low | 1 | no | 260 | coarse pointer + small viewport |

The render loop **stops** while an opaque section covers the stage, and restarts on
exit. The coverage test needs a 150 px margin — a plain `rect.bottom > scrollY`
comparison trips on sub-pixel section seams and leaves the loop stuck off.

---

## Fallbacks

- **No WebGL2** → `body.no-webgl`. Canvas and hotspots hide, a gradient stands in
  for the product, and every control still works. The page is a complete shoppable
  document without the 3D.
- **`prefers-reduced-motion`** → ticker stops, counters snap to final values,
  hero title reveals are skipped, idle spin and ring rotation are off.
- **No JavaScript** → a `<noscript>` block carries the full specification and price.

---

## Verified

`tools/qa.py <viewport>` screenshots every section and asserts console cleanliness,
canvas size, hotspot resolution and horizontal overflow. `tools/qa_interact.py`
drives colorways, sizes, the bag, the explode toggle, drag and keyboard order.
`tools/qa_degrade.py` covers reduced-motion and a WebGL-less browser.

Last run — Chromium 148, at 1920×1080, 1440×900 and 390×844:

```
60 fps · 183k tris/frame (incl. post) · high tier
console errors: none      failed requests: none      horizontal overflow: false
colorways: volt/infrared/glacier/bone/phantom all land on their exact hex
bag: opens, counts, totals, closes on Escape
reduced motion + no-WebGL: pass, no errors
```

Frame rate in these runs is software-rendered (SwiftShader in headless), so the
number reflects CI, not a GPU.

---

## Asset manifest

| id | source | licence | optimised | budget | fallback |
| --- | --- | --- | --- | --- | --- |
| `phantom-runner.glb` | generated by `tools/gen_sneaker.py` | original, this project | 1.09 MB, 89 k tris | < 2 MB | `.no-webgl` gradient |
| knit / tongue / lace / foam normal maps | generated, numpy | original | embedded in GLB (WebP) | 256² | none (material-only fallback) |
| suede / rubber roughness | generated, numpy | original | embedded in GLB (WebP) | 256² | — |
| Studio environment | `RoomEnvironment` (procedural) | MIT, Three.js | in-bundle, 0 KB | — | — |
| Archivo / Inter / JetBrains Mono | Google Fonts, latin subsets | OFL 1.1 | self-hosted, 348 KB | < 400 KB | system stack |
| Three.js r186 | npm `three@0.186.1` | MIT | vendored, ~1.4 MB | — | — |
| GSAP 3.15 + ScrollTrigger | npm `gsap@3.15.0` | GSAP standard (free) | vendored, 116 KB | — | — |
| Side graphic | original double-blade motif | original | in `OVERLAY_BLADE` | — | — |

This is a concept/demo. It is not affiliated with Nike, Inc. The side graphic is an
original blade motif, not the Swoosh; “NIKE” appears as plain type only.

# Nike-Web-Experience
