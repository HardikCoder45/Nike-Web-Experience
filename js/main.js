import { Stage, pickTier } from './stage.js';
import { Shoe, COLORWAYS } from './shoe.js';

const $  = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));
const clamp = (v, a = 0, b = 1) => Math.min(Math.max(v, a), b);
const smooth = (t) => { t = clamp(t); return t * t * (3 - 2 * t); };
const lerp = (a, b, t) => a + (b - a) * t;
const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
const hasGSAP = typeof window.gsap !== 'undefined';
const hasST = hasGSAP && typeof window.ScrollTrigger !== 'undefined';
if (hasST) gsap.registerPlugin(ScrollTrigger);

const boot = { stage: null, shoe: null, ok: false };

/* ═══════════════════════════════════════════════════════════════════════
   1 · boot
   ═══════════════════════════════════════════════════════════════════════ */
const loader = $('#loader');
const loaderBar = $('#loaderBar');
const loaderPct = $('#loaderPct');
const loaderMsg = $('#loaderMsg');

function progress(p, msg) {
  const v = Math.round(clamp(p) * 100);
  loaderBar.style.width = v + '%';
  loaderPct.textContent = v + '%';
  if (msg) loaderMsg.textContent = msg;
}

function fail(msg) {
  document.body.classList.add('no-webgl');
  progress(1, 'Static view');
  setTimeout(() => loader.classList.add('is-done'), 420);
  console.warn('[phantom] 3D unavailable —', msg);
  initUI();
}

async function init() {
  if (!document.createElement('canvas').getContext('webgl2')) {
    return fail('no WebGL2 context');
  }
  let stage;
  try {
    stage = new Stage($('#stage'), pickTier());
  } catch (e) {
    return fail(e.message);
  }
  boot.stage = stage;

  const shoe = new Shoe(stage);
  boot.shoe = shoe;
  progress(0.08, 'Loading geometry');
  try {
    await shoe.load('assets/models/phantom-runner.glb', (p) => progress(0.08 + p * 0.82, 'Loading geometry'));
  } catch (e) {
    return fail('model failed: ' + e.message);
  }

  progress(0.94, 'Compiling shaders');
  stage.frame();                      // warm pipelines before the reveal
  progress(1, 'Ready');

  boot.ok = true;
  /* small, documented inspection surface — handy for QA and for anyone
     extending the scene (see tools/qa.py) */
  window.phantom = {
    parts: Array.from(shoe.parts.keys()),
    size: { length: +shoe.length.toFixed(3), height: +shoe.height.toFixed(3) },
    upperHex: () => '#' + (shoe.mats.get('upper')?.color.getHexString() ?? '000000'),
    spin: () => view.spin,
    shot: () => activeSlot,
    explode: () => +shoe.explode.toFixed(3),
    running: () => stage.running,
    state: () => {
      const cam = stage.camera;
      const v = stage.tmpVec;
      let mn = [1e9, 1e9], mx = [-1e9, -1e9];
      stage.scene.traverse((o) => {
        if (!o.isMesh) return;
        o.updateWorldMatrix(true, false);
        const pos = o.geometry.attributes.position;
        for (let i = 0; i < pos.count; i += 5) {
          v.fromBufferAttribute(pos, i).applyMatrix4(o.matrixWorld).project(cam);
          mn[0] = Math.min(mn[0], v.x); mx[0] = Math.max(mx[0], v.x);
          mn[1] = Math.min(mn[1], v.y); mx[1] = Math.max(mx[1], v.y);
        }
      });
      return {
        cam: cam.position.toArray().map((n) => +n.toFixed(3)),
        fov: cam.fov,
        contentPos: stage.content.position.toArray().map((n) => +n.toFixed(3)),
        ndcX: [+mn[0].toFixed(2), +mx[0].toFixed(2)],
        ndcY: [+mn[1].toFixed(2), +mx[1].toFixed(2)],
        slot: activeSlot, explode: +shoe.explode.toFixed(3),
        running: stage.running, fps: stage.fps, tris: stage.tris,
      };
    },
  };

  initUI();
  initScroll();
  stage.start();
  requestAnimationFrame(() => { loader.classList.add('is-done'); revealHero(); });
}

/* ═══════════════════════════════════════════════════════════════════════
   2 · scroll choreography — one camera, one shoe, four named shots
   ═══════════════════════════════════════════════════════════════════════ */
const SHOTS = {
  hero:    { r: 2.52, th: -0.42, ph: 1.33, ox:  0.46, oy: 0.15, spin: 0.045 },
  dissect: { r: 3.00, th: -0.06, ph: 1.50, ox:  0.00, oy: -0.02, spin: 0 },
  buy:     { r: 2.46, th: -2.68, ph: 1.36, ox: -0.58, oy: 0.12, spin: 0.07 },
  far:     { r: 4.30, th:  1.10, ph: 1.20, ox:  1.02, oy: 0.34, spin: 0.03 },
};
const TARGET = [0, 0.17, 0];

/* One value object, one writer per property. Overlapping scrub tweens on the
   same object would otherwise fight, so each section owns a distinct slot and
   the active one is chosen from scroll position. */
const shots = {
  hero:    { ...SHOTS.hero },
  dissect: { ...SHOTS.dissect },
  buy:     { ...SHOTS.buy },
  far:     { ...SHOTS.far },
};
const shot = { ...SHOTS.hero };
const view = { spin: 0, ox: 0, oy: 0 };
let explodeOverride = null;

function copyShot(dst, src) {
  Object.keys(dst).forEach((k) => { dst[k] = src[k]; });
}

function initScroll() {
  const { stage, shoe } = boot;

  if (!hasST) {                        // no ScrollTrigger: hold the hero shot
    stage.setShot({ radius: shot.r, theta: shot.th, phi: shot.ph, target: TARGET });
    return;
  }

  const scrub = (slot, keys, trig, start, end, s = 0.7) => gsap.to(shots[slot], {
    ...SHOTS[slot], ...keys, ease: 'power2.inOut', duration: 1,
    scrollTrigger: { trigger: trig, start, end, scrub: s },
  });

  /* hero -> dissect as the hero scrolls away */
  scrub('hero', {}, '.hero', 'top top', 'bottom 25%', 0.6);

  /* anatomy owns its own explode + hotspots, camera holds the side view */
  ScrollTrigger.create({
    trigger: '#anatomy',
    start: 'top 72%', end: 'bottom 78%',
    onUpdate: (self) => {
      if (explodeOverride === null) shoe.setExplode(smooth(clamp((self.progress - 0.04) / 0.5)));
      setHotspots(self.progress > 0.14);
      stage.atmoTarget = 0.32;
    },
    onLeave: () => { if (explodeOverride === null) shoe.setExplode(1); stage.atmoTarget = 1; },
    onEnterBack: () => { if (explodeOverride === null) shoe.setExplode(0); stage.atmoTarget = 0.32; },
  });
  /* any entry into the configurator band guarantees a reassembled shoe */
  ScrollTrigger.create({
    trigger: '#colorway', start: 'top 90%', end: 'top bottom',
    onEnter: () => { if (explodeOverride === null) shoe.setExplode(0); },
    onEnterBack: () => { if (explodeOverride === null) shoe.setExplode(0); },
  });
  scrub('dissect', {}, '#anatomy', 'top 80%', 'top 20%', 0.7);

  /* reassembled and swung to the opposite flank for the configurator */
  scrub('buy', {}, '#colorway', 'top 78%', 'top 14%', 0.7);
  ScrollTrigger.create({
    trigger: '#colorway', start: 'top 95%', end: 'bottom top',
    onUpdate: (self) => { if (explodeOverride === null && self.progress > 0.01) shoe.setExplode(0); },
  });

  /* story pushes it into the distance behind the type */
  scrub('far', {}, '#story', 'top 95%', 'top -15%', 0.8);

  ['#tech', '.story', '.foot', '#anatomy', '#colorway'].forEach((sel) => {
    ScrollTrigger.create({ trigger: sel, start: 'top bottom', end: 'bottom top',
      onToggle: measureSections });
  });
}

/* ── section geometry, cached so the render loop never thrashes layout ── */
const BANDS = [];
function measureSections() {
  BANDS.length = 0;
  const vh = innerHeight;
  [['#story', 'far'], ['#colorway', 'buy'], ['#anatomy', 'dissect']].forEach(([sel, slot]) => {
    const r = $(sel).getBoundingClientRect();
    BANDS.push({ slot, top: r.top + scrollY, bottom: r.bottom + scrollY });
  });
  OPAQUE.length = 0;
  ['#tech', '.story', '.foot'].forEach((sel) => {
    const r = $(sel).getBoundingClientRect();
    OPAQUE.push({ top: r.top + scrollY, bottom: r.bottom + scrollY });
  });
  ANATOMY.top = $('#anatomy').getBoundingClientRect().top + scrollY;
  ANATOMY.bottom = $('#anatomy').getBoundingClientRect().bottom + scrollY;
}
const OPAQUE = [];
const ANATOMY = { top: 0, bottom: 0 };

let activeSlot = 'hero';
let rafOn = false;
let measureDirty = true;

function pickSlot() {
  const y = scrollY + innerHeight * 0.45;
  let slot = 'hero';
  for (const b of BANDS) if (y >= b.top && y < b.bottom) { slot = b.slot; break; }
  if (slot === 'hero' && y >= ANATOMY.top) slot = 'dissect';
  return slot;
}

/* the stage is fully hidden behind opaque sections - stop burning frames */
function syncRenderLoop() {
  const y0 = scrollY;
  const y1 = scrollY + innerHeight;
  /* require real coverage, not a sub-pixel overlap at a section seam */
  const MARGIN = 150;
  const hidden = OPAQUE.some((b) => b.top < y1 - MARGIN && b.bottom > y0 + MARGIN);
  if (hidden) { if (rafOn) { boot.stage.stop(); rafOn = false; } }
  else if (!rafOn) { boot.stage.start(); rafOn = true; }
}

/* our own rAF so shoe animation + framing stay in step with the render loop */
function frame() {
  requestAnimationFrame(frame);
  const { stage, shoe } = boot;
  if (!stage) return;

  if (measureDirty) { measureSections(); measureDirty = false; }
  activeSlot = pickSlot();
  syncRenderLoop();
  if (!stage.running) return;

  const dt = stage.dt || 0.016;
  copyShot(shot, shots[activeSlot]);

  if (!reduced) view.spin += dt * shot.spin;
  shoe.update(dt);

  /* portrait needs a longer lens distance, not a wider one, or the toe
     blows out from perspective */
  const mobile = innerWidth < 861;
  const scale = mobile ? 1.78 : 1;

  stage.setShot({ radius: shot.r * scale, theta: shot.th + view.spin, phi: shot.ph, target: TARGET });

  const tx = mobile ? 0.04 : shot.ox;
  const ty = mobile ? shot.oy + 0.15 : shot.oy;
  view.ox = lerp(view.ox, tx, 0.05);
  view.oy = lerp(view.oy, ty, 0.05);
  stage.frameOffset.set(view.ox, view.oy);

  projectHotspots();
}

addEventListener('scroll', () => { measureDirty = true; }, { passive: true });
addEventListener('resize', () => { measureDirty = true; }, { passive: true });

/* ═══════════════════════════════════════════════════════════════════════
   3 · hotspots — real 3D anchors projected to screen
   ═══════════════════════════════════════════════════════════════════════ */
const hotspotEls = $$('.hotspot');
let hotspotsLive = false;

function setHotspots(on) {
  if (on === hotspotsLive) return;
  hotspotsLive = on;
  hotspotEls.forEach((el, i) => {
    el.classList.toggle('is-on', on);
    el.style.transitionDelay = on ? (0.05 * i + 's') : '0s';
  });
}

function projectHotspots() {
  const { stage, shoe } = boot;
  if (!shoe) return;
  const v = stage.tmpVec;
  const live = hotspotsLive && ANATOMY.top < scrollY + innerHeight && ANATOMY.bottom > scrollY;
  /* keep every label clear of the scrubber, measured rather than guessed */
  const bar = $('.anatomy__bar');
  const barTop = bar ? bar.getBoundingClientRect().top : innerHeight;
  const floor = Math.min(innerHeight - 84, barTop - 74);

  /* the labels are absolutely positioned inside .hotspots, which is itself
     offset inside .anatomy__viewport. Anchors project to *window* space, so
     the difference has to come back out or every label lands low. */
  const host = $('.hotspots').getBoundingClientRect();

  const laid = [];
  for (const el of hotspotEls) {
    const name = el.dataset.part;
    if (!shoe.parts.has(name)) { el.remove(); continue; }
    if (!live) { el.style.visibility = 'hidden'; continue; }

    shoe.anchor(name, v);
    v.project(stage.camera);
    if (v.z >= 1 || Math.abs(v.x) > 1.3 || Math.abs(v.y) > 1.3) {
      el.style.visibility = 'hidden';
      continue;
    }
    /* the label hangs off its anchor on a fixed leader, so the set reads as a
       diagram instead of a stack that shifts as the product rotates */
    const ox = parseFloat(el.dataset.ox || 0);
    const oy = parseFloat(el.dataset.oy || 0);
    const ax = (v.x * 0.5 + 0.5) * innerWidth;
    const ay = (-v.y * 0.5 + 0.5) * innerHeight;
    const x = clamp(ax + ox, 96, innerWidth - 96) - host.left;
    const y = clamp(ay + oy, 78, floor) - host.top;
    laid.push({ el, x, y, side: ox < 0 ? -1 : 1, ax, ay });
  }

  /* last-resort separation if two leaders still land on top of each other */
  laid.sort((a, b) => a.y - b.y);
  for (let i = 1; i < laid.length; i++) {
    if (Math.abs(laid[i].x - laid[i - 1].x) < 200 && laid[i].y - laid[i - 1].y < 46) {
      laid[i].y = laid[i - 1].y + 46;
    }
  }
  laid.forEach((l) => (l.y = Math.min(l.y, floor)));

  for (const l of laid) {
    l.el.style.visibility = 'visible';
    l.el.classList.toggle('is-right', l.side > 0);
    const dir = l.side > 0 ? 'translate(0,-50%)' : 'translate(-100%,-50%)';
    l.el.style.transform = `translate(${l.x.toFixed(1)}px,${l.y.toFixed(1)}px) ${dir}`;
  }
}

/* ═══════════════════════════════════════════════════════════════════════
   4 · drag to orbit (window-level so links stay clickable)
   ═══════════════════════════════════════════════════════════════════════ */
function initDrag() {
  let dragging = false, lx = 0, id = null;
  const hint = $('#dragHint');
  const interactive = (t) => t && t.closest('a,button,input,label,.size,.swatch,.cart,.anatomy__bar,.sub__row,fieldset,.foot');

  addEventListener('pointerdown', (e) => {
    if (!boot.ok || e.button !== 0 || interactive(e.target)) return;
    dragging = true; lx = e.clientX; id = e.pointerId;
    if (hint) hint.style.opacity = '0';
  }, { passive: true });

  addEventListener('pointermove', (e) => {
    if (!dragging) return;
    view.spin += (e.clientX - lx) * 0.0055;
    lx = e.clientX;
    if (e.pointerId === id) e.preventDefault();
  }, { passive: false });

  const end = () => { dragging = false; };
  addEventListener('pointerup', end, { passive: true });
  addEventListener('pointercancel', end, { passive: true });

  addEventListener('keydown', (e) => {
    if (e.target.closest('input,textarea,select')) return;
    if (e.key === 'ArrowLeft')  { view.spin -= 0.16; e.preventDefault(); }
    if (e.key === 'ArrowRight') { view.spin += 0.16; e.preventDefault(); }
  });
}

/* ═══════════════════════════════════════════════════════════════════════
   5 · UI
   ═══════════════════════════════════════════════════════════════════════ */
const SIZES = [7, 7.5, 8, 8.5, 9, 9.5, 10, 10.5, 11, 12, 13];
const SOLD_OUT = new Set([7, 12]);
const cart = [];
let currentCW = 'phantom';
let chosenSize = 9;

function initUI() {
  initNav();
  initTicker();
  initReveals();
  initCounters();
  initSwatches();
  initSizes();
  initCart();
  initExplodeToggle();
  initSub();
  if (boot.ok) { initDrag(); frame(); trackPerf(); }
  addEventListener('load', () => { if (hasST) ScrollTrigger.refresh(); });
}

/* nav */
function initNav() {
  const nav = $('#nav'), burger = $('#burger'), sheet = $('#sheet');
  const onScroll = () => nav.classList.toggle('is-stuck', scrollY > 24);
  addEventListener('scroll', onScroll, { passive: true });
  onScroll();

  burger.addEventListener('click', () => {
    const open = burger.getAttribute('aria-expanded') === 'true';
    burger.setAttribute('aria-expanded', String(!open));
    sheet.classList.toggle('is-open', !open);
  });
  sheet.addEventListener('click', (e) => {
    if (e.target.tagName === 'A') {
      sheet.classList.remove('is-open');
      burger.setAttribute('aria-expanded', 'false');
    }
  });

  $$('[data-scroll]').forEach((b) => b.addEventListener('click', () => {
    const t = $(b.dataset.scroll);
    if (t) t.scrollIntoView({ behavior: reduced ? 'auto' : 'smooth', block: 'start' });
  }));
}

/* ticker */
const TICKER = ['Full-length air', '38mm stack', 'Supercritical EVA', 'Zoned engineered knit',
  '248g', '320ml nitrogen', 'Rigid TPU heel clip', 'Members get 10% off'];

function initTicker() {
  const row = $('#ticker');
  if (!row) return;
  const html = TICKER.map((t) => `<span>${t}</span>`).join('');
  row.innerHTML = html + html + html;
  if (reduced || !hasGSAP) return;
  gsap.to(row, { x: -(row.scrollWidth / 3), duration: 36, ease: 'none', repeat: -1 });
}

/* reveals */
function revealHero() {
  if (reduced || !hasGSAP) {
    $$('.hero__title .line>span').forEach((s) => (s.style.transform = 'none'));
    return;
  }
  gsap.to('.hero__title .line>span', { y: 0, duration: 1.15, ease: 'expo.out', stagger: 0.09, delay: 0.1 });
  gsap.from('.hero__eyebrow, .hero__lede, .hero__cta, .hero__facts',
    { y: 22, opacity: 0, duration: 0.9, ease: 'expo.out', stagger: 0.07, delay: 0.34 });
}

function initReveals() {
  const items = $$('.sec-head, .card, .cmp, .story__body, .foot__cols, .buy__panel, .anatomy__bar');
  items.forEach((el) => el.classList.add('reveal'));
  if (reduced || !hasST) { items.forEach((el) => el.classList.add('is-in')); return; }
  items.forEach((el) => ScrollTrigger.create({
    trigger: el, start: 'top 90%', once: true, onEnter: () => el.classList.add('is-in'),
  }));
}

/* counters */
function initCounters() {
  const run = (el) => {
    const to = parseFloat(el.dataset.count);
    const pre = el.dataset.prefix || '';
    const suf = el.dataset.suffix || '';
    if (reduced || !hasGSAP) { el.textContent = pre + to + suf; return; }
    const o = { v: 0 };
    gsap.to(o, { v: to, duration: 1.5, ease: 'expo.out',
      onUpdate: () => (el.textContent = pre + Math.round(o.v) + suf) });
  };
  $$('[data-count]').forEach((el) => {
    if (!hasST) { run(el); return; }
    ScrollTrigger.create({ trigger: el, start: 'top 94%', once: true, onEnter: () => run(el) });
  });
}

/* colorways */
function initSwatches() {
  $$('.swatch').forEach((btn) => btn.addEventListener('click', () => {
    const cw = COLORWAYS[btn.dataset.cw];
    if (!cw) return;
    currentCW = btn.dataset.cw;
    $$('.swatch').forEach((b) => {
      const on = b === btn;
      b.classList.toggle('is-on', on);
      b.setAttribute('aria-checked', String(on));
    });
    $('#mStyle').textContent = cw.style;
    $('#mName').textContent = cw.label;
    $('#mPrice').textContent = '$' + cw.price;
    if (boot.ok) boot.shoe.applyColorway(cw);
  }));
}

/* sizes */
function initSizes() {
  const row = $('#sizes');
  row.innerHTML = SIZES.map((s) => {
    const out = SOLD_OUT.has(s);
    return `<button type="button" class="size${s === chosenSize ? ' is-on' : ''}" data-s="${s}"${out ? ' disabled aria-label="size ' + s + ' sold out"' : ''}>${s}</button>`;
  }).join('');
  row.addEventListener('click', (e) => {
    const b = e.target.closest('.size');
    if (!b || b.disabled) return;
    chosenSize = parseFloat(b.dataset.s);
    $$('.size', row).forEach((x) => x.classList.toggle('is-on', x === b));
  });
}

/* explode toggle */
function initExplodeToggle() {
  const btn = $('#explodeToggle');
  const bar = $('#explodeBar');
  const val = $('#explodeVal');
  let on = false;
  btn.addEventListener('click', () => {
    on = !on;
    btn.setAttribute('aria-pressed', String(on));
    btn.textContent = on ? 'Assemble view' : 'Explode view';
    explodeOverride = on ? 1 : 0;
    const sec = $('#anatomy');
    if (on && sec.getBoundingClientRect().top > innerHeight * 0.4) {
      sec.scrollIntoView({ behavior: reduced ? 'auto' : 'smooth' });
    }
  });
  const tick = () => {
    const e = boot.shoe ? boot.shoe.explode : 0;
    bar.style.width = (e * 100).toFixed(1) + '%';
    val.textContent = Math.round(e * 100) + '%';
    requestAnimationFrame(tick);
  };
  tick();
}

/* cart */
function initCart() {
  const panel = $('#cart'), scrim = $('#scrim');
  const open = (v) => {
    panel.classList.toggle('is-open', v);
    scrim.classList.toggle('is-open', v);
    panel.setAttribute('aria-hidden', String(!v));
    $('#cartBtn').setAttribute('aria-expanded', String(v));
    document.body.classList.toggle('is-locked', v);
    if (v) $('#cartClose').focus(); else $('#cartBtn').focus();
  };
  $('#cartBtn').addEventListener('click', () => open(true));
  $('#cartClose').addEventListener('click', () => open(false));
  scrim.addEventListener('click', () => open(false));
  addEventListener('keydown', (e) => { if (e.key === 'Escape') open(false); });

  $('#addBtn').addEventListener('click', (e) => {
    const b = e.currentTarget;
    cart.push({ cw: currentCW, size: chosenSize, price: COLORWAYS[currentCW].price });
    renderCart();
    b.classList.add('is-done');
    b.textContent = 'Added to bag ✓';
    setTimeout(() => { b.classList.remove('is-done'); b.textContent = 'Add to bag'; }, 1700);
    open(true);
  });
  renderCart();
}

function renderCart() {
  const box = $('#cartItems');
  $('#cartCount').textContent = cart.length;
  $('#cartTotal').textContent = '$' + cart.reduce((a, c) => a + c.price, 0);
  if (!cart.length) { box.innerHTML = '<p class="cart__empty">Your bag is empty.</p>'; return; }
  box.innerHTML = cart.map((c) => {
    const cw = COLORWAYS[c.cw];
    return `<div class="citem">
      <span class="citem__chip" style="background:linear-gradient(135deg,${cw.upper} 0 46%,${cw.accent} 46% 62%,${cw.overlay} 62% 100%)"></span>
      <div><h4>Air Max Phantom</h4><p>${cw.label} · US ${c.size}</p></div>
      <b>$${c.price}</b>
    </div>`;
  }).join('');
}

/* newsletter */
function initSub() {
  const f = $('#subForm'), msg = $('#subMsg'), input = $('#email');
  f.addEventListener('submit', (e) => {
    e.preventDefault();
    const ok = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(input.value.trim());
    msg.textContent = ok ? '✓ You’re on the list. Watch your inbox.' : 'Please enter a valid email address.';
    msg.style.color = ok ? 'var(--volt)' : 'var(--ir)';
    if (ok) input.value = '';
  });
}

/* perf readout */
function trackPerf() {
  const el = $('#perf');
  if (!el) return;
  setTimeout(() => {
    el.textContent = `${boot.stage.fps} fps · ${((boot.stage.tris || 0) / 1000).toFixed(0)}k tris · ${boot.stage.tier} tier`;
  }, 2800);
}

/* go */
if (document.readyState === 'loading') addEventListener('DOMContentLoaded', init);
else init();