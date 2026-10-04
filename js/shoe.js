import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { MeshoptDecoder } from 'three/addons/libs/meshopt_decoder.module.js';

/* ── colorways ─────────────────────────────────────────────────────────────
   Every value here is a real base colour pushed onto the material at runtime,
   so the swatches re-light and re-shade the actual model — nothing is faked
   with an image swap. Order of the ramp: upper / overlay / accent / midsole /
   outsole, plus lace, tongue, lining and eyelet tints.                     */
export const COLORWAYS = {
  phantom: {
    label: 'Phantom Black / Volt', style: 'CU2320-001', price: 190,
    upper: '#c9c6bc', overlay: '#16181c', accent: '#d7ff2f', midsole: '#cbc7bd',
    outsole: '#16181c', lace: '#e8e5db', tongue: '#8d8981', lining: '#131519',
    eyelet: '#8b8f95', air: '#a9d8ea',
  },
  bone: {
    label: 'Bone / Sail', style: 'CU2320-014', price: 190,
    upper: '#cbc5b8', overlay: '#a89e8c', accent: '#7a6d56', midsole: '#cfc9bb',
    outsole: '#9c9282', lace: '#dcd6c8', tongue: '#c1b9aa', lining: '#4a453d',
    eyelet: '#b8b2a6', air: '#cfe2ea',
  },
  volt: {
    label: 'Volt / Black', style: 'CU2320-100', price: 210,
    upper: '#a8cc20', overlay: '#1a1c20', accent: '#1a1c20', midsole: '#202328',
    outsole: '#6f8400', lace: '#a8cc20', tongue: '#93b41c', lining: '#101114',
    eyelet: '#3a3d42', air: '#cfe86a',
  },
  infrared: {
    label: 'Infrared', style: 'CU2320-220', price: 200,
    upper: '#c2401f', overlay: '#221416', accent: '#d9a68c', midsole: '#cdc4b8',
    outsole: '#221416', lace: '#d6cec4', tongue: '#b13b1c', lining: '#241416',
    eyelet: '#6e5a52', air: '#ffd0b4',
  },
  glacier: {
    label: 'Glacier', style: 'CU2320-330', price: 195,
    upper: '#7fa6b8', overlay: '#c2d2d8', accent: '#2f5a6d', midsole: '#c6d4da',
    outsole: '#2f5a6d', lace: '#d8e4e9', tongue: '#759dad', lining: '#22333c',
    eyelet: '#9fb3bd', air: '#d6eef7',
  },
};

/* ── explode choreography: offset + stagger per part ──────────────────── */
const EXPLODE = {
  UNIT_OUTSOLE:      { d: [0, -0.165, 0],      t: 0.00 },
  UNIT_MIDSOLE:      { d: [0, -0.078, 0],      t: 0.06 },
  UNIT_AIR:          { d: [0, -0.020, 0.075],  t: 0.12 },
  UPPER_MAIN:        { d: [0,  0.086, 0],      t: 0.18 },
  UPPER_TONGUE:      { d: [0.014, 0.150, 0],   t: 0.22 },
  OVERLAY_TOE:       { d: [0.135, 0.030, 0],   t: 0.28 },
  OVERLAY_HEEL:      { d: [-0.135, 0.044, 0],  t: 0.28 },
  OVERLAY_BLADE:     { d: [0, 0.014, 0.150],   t: 0.34 },
  OVERLAY_BLADE_M:   { d: [0, 0.014, -0.150],  t: 0.34 },
  OVERLAY_PIN:       { d: [0, -0.024, 0.118],  t: 0.38 },
  OVERLAY_PIN_M:     { d: [0, -0.024, -0.118], t: 0.38 },
  DETAIL_COLLAR:     { d: [0, 0.190, 0],       t: 0.42 },
  DETAIL_HEELTAB:    { d: [-0.085, 0.225, 0],  t: 0.46 },
  DETAIL_LACES:      { d: [0.018, 0.215, 0],   t: 0.50 },
  DETAIL_EYELETS:    { d: [0, 0.140, 0],       t: 0.54 },
  LOGO_TONGUE:       { d: [0.018, 0.215, 0],   t: 0.50 },
  LOGO_HEEL:         { d: [-0.085, 0.225, 0],  t: 0.46 },
};

const ROLE = {
  MAT_Upper: 'upper', MAT_Tongue: 'tongue', MAT_Overlay: 'overlay',
  MAT_Collar: 'overlay', MAT_Lining: 'lining', MAT_Midsole: 'midsole',
  MAT_Outsole: 'outsole', MAT_Air: 'air', MAT_Accent: 'accent',
  MAT_Logo: 'logo', MAT_Lace: 'lace', MAT_Eyelet: 'eyelet',
};

export class Shoe {
  constructor(stage) {
    this.stage = stage;
    this.root = new THREE.Group();
    this.parts = new Map();
    this.mats = new Map();
    this.explode = 0;
    this.explodeTarget = 0;
    this.colorway = COLORWAYS.phantom;
    this._target = new THREE.Color();
    this.pivot = new THREE.Group();
    this.root.add(this.pivot);
    stage.content.add(this.root);
  }

  async load(url, onProgress) {
    const loader = new GLTFLoader();
    loader.setMeshoptDecoder(MeshoptDecoder);
    const gltf = await loader.loadAsync(url, (e) => {
      if (onProgress && e.lengthComputable) onProgress(e.loaded / e.total);
    });

    const box = new THREE.Box3().setFromObject(gltf.scene);
    const size = box.getSize(new THREE.Vector3());
    const centre = box.getCenter(new THREE.Vector3());
    this.length = size.x;
    this.height = size.y;

    gltf.scene.traverse((o) => {
      /* a multi-material primitive arrives as a Group of meshes (UPPER_MAIN is
         one), so treat "all children are meshes" as a movable part too */
      const isPart = o.isMesh ||
        (o.type === 'Group' && o.children.length > 0 && o.children.every((c) => c.isMesh));
      if (!isPart) return;
      o.castShadow = false;
      o.receiveShadow = false;
      o.frustumCulled = false;
      o.userData.home = o.position.clone();
      o.userData.isMesh = o.isMesh;
      this.parts.set(o.name, o);

      const mats = o.isMesh ? (Array.isArray(o.material) ? o.material : [o.material])
                            : o.children.flatMap((c) =>
                                Array.isArray(c.material) ? c.material : [c.material]);
      const list = mats;
      list.forEach((m) => {
        if (!m || !m.color) return;
        m.envMapIntensity = 1.0;
        if (m.normalScale) m.normalScale.set(1.15, 1.15);
        const role = ROLE[m.name];
        if (role && !this.mats.has(role)) this.mats.set(role, m);
        this.mats.set(m.name, m);
      });
    });

    this.pivot.add(gltf.scene);
    this.pivot.position.set(-centre.x, -box.min.y, -centre.z);
    gltf.scene.position.set(0, 0, 0);
    this.box = box;
    this.applyColorway(this.colorway);
    return this;
  }

  /* ── colorway ─────────────────────────────────────────────────────────
     A swatch is a real material change on the live model. The change is
     animated by interpolating every role from its current colour to the new
     one, so switching mid-transition still lands on the right value instead of
     stepping 16% toward a target and never arriving. */
  applyColorway(cw) {
    this.colorway = cw;
    /* THREE.Color(string) already converts sRGB -> the linear working space;
       calling convertSRGBToLinear() on top of that darkens everything twice. */
    const targets = {
      upper: cw.upper, tongue: cw.tongue, overlay: cw.overlay, lining: cw.lining,
      midsole: cw.midsole, outsole: cw.outsole, accent: cw.accent,
      logo: cw.upper, lace: cw.lace, eyelet: cw.eyelet, air: cw.air,
    };
    const strength = { logo: 0.55 };      /* print reads as a tint of the upper */

    if (!this.blend) this.blend = new Map();
    Object.entries(targets).forEach(([r, hex]) => {
      const m = this.mats.get(r);
      if (!m || !m.color) return;
      this.blend.set(r, {
        from: m.color.clone(),
        to: new THREE.Color(hex),
        mix: strength[r] ?? 1,
      });
    });
    this.blendProgress = 0;
  }

  stepColorway(dt) {
    if (!this.blend || this.blendProgress >= 1) return;
    this.blendProgress = Math.min(1, this.blendProgress + dt * 2.6);
    const e = this.blendProgress;
    const k = e * e * (3 - 2 * e);            /* smoothstep, ~0.38s */
    this.blend.forEach((v, r) => {
      const m = this.mats.get(r);
      if (m && m.color) m.color.lerpColors(v.from, v.to, k * v.mix);
    });
  }

  /* ── exploded technical view ──────────────────────────────────────── */
  setExplode(v, immediate = false) {
    this.explodeTarget = THREE.MathUtils.clamp(v, 0, 1);
    if (immediate) this.explode = this.explodeTarget;
  }

  get exploded() { return this.explodeTarget > 0.5; }

  /* hotspot anchors in world space */
  anchor(name, out = new THREE.Vector3()) {
    const p = this.parts.get(name);
    if (!p) return out.set(0, 0.2, 0);
    p.updateWorldMatrix(true, false);
    return out.setFromMatrixPosition(p.matrixWorld);
  }

  update(dt) {
    this.stepColorway(dt);
    const k = 1 - Math.pow(0.002, dt);
    this.explode += (this.explodeTarget - this.explode) * k;

    if (Math.abs(this.explode) > 0.0005) {
      this.parts.forEach((o, name) => {
        const cfg = EXPLODE[name];
        if (!cfg) return;
        const local = THREE.MathUtils.clamp((this.explode - cfg.t) / (1 - cfg.t), 0, 1);
        const e = local * local * (3 - 2 * local);   // smoothstep
        o.position.set(
          o.userData.home.x + cfg.d[0] * e,
          o.userData.home.y + cfg.d[1] * e,
          o.userData.home.z + cfg.d[2] * e,
        );
      });
    }
  }
}