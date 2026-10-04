import * as THREE from 'three';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';
import { EffectComposer } from 'three/addons/postprocessing/EffectComposer.js';
import { RenderPass } from 'three/addons/postprocessing/RenderPass.js';
import { UnrealBloomPass } from 'three/addons/postprocessing/UnrealBloomPass.js';
import { OutputPass } from 'three/addons/postprocessing/OutputPass.js';

/* ── quality tiers ─────────────────────────────────────────────────────── */
export const TIERS = {
  high:   { dpr: [1, 1.75], bloom: true,  dust: 1400, rings: 3, shadows: true },
  medium: { dpr: [1, 1.35], bloom: true,  dust: 700,  rings: 2, shadows: false },
  low:    { dpr: [1, 1],    bloom: false, dust: 260,  rings: 2, shadows: false },
};

export function pickTier() {
  const mem = navigator.deviceMemory || 4;
  const cores = navigator.hardwareConcurrency || 4;
  const small = Math.min(innerWidth, innerHeight) < 700;
  const coarse = matchMedia('(pointer:coarse)').matches;
  if (coarse && small) return 'low';
  if (mem <= 4 || cores <= 4) return 'medium';
  return 'high';
}

/* ── camera state, lerped every frame ──────────────────────────────────── */
const sph = (r, theta, phi) => new THREE.Spherical(r, phi, theta);

export class Stage {
  constructor(canvas, tierName) {
    this.canvas = canvas;
    this.tier = TIERS[tierName] ? tierName : 'medium';
    this.q = TIERS[this.tier];
    this.reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;

    this.renderer = new THREE.WebGLRenderer({
      canvas,
      antialias: this.tier === 'high',
      alpha: true,
      powerPreference: 'high-performance',
      stencil: false,
    });
    this.renderer.setPixelRatio(Math.min(devicePixelRatio, this.q.dpr[1]));
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 0.82;
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;

    this.scene = new THREE.Scene();
    this.scene.fog = new THREE.FogExp2(0x08090b, 0.072);

    this.camera = new THREE.PerspectiveCamera(34, 1, 0.05, 40);
    this.camTarget = new THREE.Vector3(0, 0, 0);
    this.camLook = new THREE.Vector3(0, 0, 0);
    this.from = { s: sph(3.1, 0.9, 1.28), t: new THREE.Vector3(0, 0.06, 0) };
    this.to = { s: sph(3.1, 0.9, 1.28), t: new THREE.Vector3(0, 0.06, 0) };
    this._v = new THREE.Vector3();

    this.buildEnvironment();
    this.buildLights();
    this.buildAtmosphere();

    this.content = new THREE.Group();
    this.scene.add(this.content);

    /* view-space nudge so the product can sit clear of the copy column */
    this.frameOffset = new THREE.Vector2();
    this._r = new THREE.Vector3();
    this._u = new THREE.Vector3();
    this.tmpVec = new THREE.Vector3();

    if (this.q.bloom) this.buildComposer();

    this.clock = new THREE.Clock();
    this.running = false;          /* start() owns the loop; don't pre-arm the guard */
    this.dt = 0.016;
    this.tris = 0;
    this.atmoDim = 1;
    this.atmoTarget = 1;
    this._frames = 0;
    this._fpsT = 0;
    this.fps = 60;

    addEventListener('resize', () => this.resize(), { passive: true });
    this.resize();
  }

  /* studio reflections with zero external HDR downloads */
  buildEnvironment() {
    const pmrem = new THREE.PMREMGenerator(this.renderer);
    pmrem.compileEquirectangularShader();
    this.envRT = pmrem.fromScene(new RoomEnvironment(), 0.035);
    this.scene.environment = this.envRT.texture;
    this.scene.environmentIntensity = 0.34;
    pmrem.dispose();
  }

  buildLights() {
    const key = new THREE.DirectionalLight(0xfff2dd, 1.5);
    key.position.set(1.9, 2.5, 1.9);
    const fill = new THREE.DirectionalLight(0x9dbcff, 0.34);
    fill.position.set(-2.4, 0.8, 1.6);
    const rim = new THREE.DirectionalLight(0xeaf2ff, 0.95);
    rim.position.set(-1.5, 1.4, -2.5);
    const edge = new THREE.DirectionalLight(0xd7ff2f, 0.40);   /* brand kicker */
    edge.position.set(-0.4, -0.8, -1.6);
    const under = new THREE.PointLight(0x6f8bff, 0.7, 4.5, 2);
    under.position.set(0, -0.85, 0.5);
    this.scene.add(key, fill, rim, edge, under);

    /* camera-relative fill: the world key stays put as the product orbits, but
       a viewer-anchored fill keeps the side facing camera out of the dark */
    const camFill = new THREE.DirectionalLight(0xfff4e6, 0.72);
    camFill.position.set(0.8, 1.1, 1.4);
    const camRim = new THREE.DirectionalLight(0xdfe9ff, 0.40);
    camRim.position.set(-1.1, 0.5, -0.8);
    this.camera.add(camFill, camRim);
    this.scene.add(this.camera);
    this.lights = { key, fill, rim, edge, under, camFill, camRim };
  }

  /* the "reveal chamber": light rings, a floor grid, drifting dust */
  buildAtmosphere() {
    const atmo = new THREE.Group();
    this.atmo = atmo;
    this.scene.add(atmo);

    const ringMat = new THREE.MeshBasicMaterial({
      color: 0xd7ff2f, transparent: true, opacity: 0.5,
      blending: THREE.AdditiveBlending, depthWrite: false, toneMapped: false,
    });
    this.rings = [];
    const specs = [[0.62, 0.0034, 0.15], [0.80, 0.0024, 0.09], [1.00, 0.0026, 0.05]];
    specs.slice(0, this.q.rings).forEach(([r, tube, op], i) => {
      const m = new THREE.Mesh(
        new THREE.TorusGeometry(r, tube, 6, 128),
        ringMat.clone(),
      );
      m.material.opacity = op;
      m.userData.base = op;
      m.rotation.x = Math.PI / 2 + (i - 1) * 0.16;
      m.rotation.z = i * 0.4;
      atmo.add(m);
      this.rings.push(m);
    });

    /* floor: radial rings + spokes, faded to nothing */
    const floorMat = new THREE.ShaderMaterial({
      transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
      uniforms: { uColor: { value: new THREE.Color(0x8ea3c8) }, uOpacity: { value: 0.34 } },
      vertexShader: /* glsl */`
        varying vec2 vP;
        void main(){ vP = position.xy; gl_Position = projectionMatrix * modelViewMatrix * vec4(position,1.0); }`,
      fragmentShader: /* glsl */`
        precision highp float;
        varying vec2 vP; uniform vec3 uColor; uniform float uOpacity;
        void main(){
          float r = length(vP);
          if (r > 2.1) discard;
          float rings = abs(sin(r * 26.0)) * 0.055;
          float a = atan(vP.y, vP.x);
          float spokes = abs(sin(a * 24.0)) * 0.010 * smoothstep(2.1, 0.4, r);
          float fade = pow(1.0 - clamp(r / 2.1, 0.0, 1.0), 2.2);
          gl_FragColor = vec4(uColor, (rings + spokes) * fade * uOpacity);
        }`,
    });
    const floor = new THREE.Mesh(new THREE.PlaneGeometry(5, 5), floorMat);
    floor.rotation.x = -Math.PI / 2;
    floor.position.y = -0.78;
    atmo.add(floor);
    this.floor = floor;

    /* dust motes */
    const n = this.q.dust;
    const pos = new Float32Array(n * 3);
    const seed = new Float32Array(n);
    for (let i = 0; i < n; i++) {
      const r = 0.45 + Math.random() * 1.9;
      const th = Math.random() * Math.PI * 2;
      pos[i * 3] = Math.cos(th) * r;
      pos[i * 3 + 1] = -0.7 + Math.random() * 2.2;
      pos[i * 3 + 2] = Math.sin(th) * r;
      seed[i] = Math.random();
    }
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.BufferAttribute(pos, 3));
    g.setAttribute('aSeed', new THREE.BufferAttribute(seed, 1));
    const dust = new THREE.Points(g, new THREE.ShaderMaterial({
      transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
      uniforms: {
        uTime: { value: 0 }, uColor: { value: new THREE.Color(0xdfe6ff) },
        uPR: { value: Math.min(devicePixelRatio, this.q.dpr[1]) },
      },
      vertexShader: /* glsl */`
        attribute float aSeed; uniform float uTime; uniform float uPR;
        varying float vA;
        void main(){
          vec3 p = position;
          p.y += sin(uTime * 0.18 + aSeed * 31.4) * 0.16;
          p.x += cos(uTime * 0.13 + aSeed * 17.7) * 0.12;
          vec4 mv = modelViewMatrix * vec4(p, 1.0);
          gl_PointSize = (1.6 + aSeed * 3.4) * uPR * (2.2 / -mv.z);
          vA = 0.16 + aSeed * 0.5;
          gl_Position = projectionMatrix * mv;
        }`,
      fragmentShader: /* glsl */`
        precision mediump float; uniform vec3 uColor; varying float vA;
        void main(){
          float d = length(gl_PointCoord - 0.5);
          if (d > 0.5) discard;
          gl_FragColor = vec4(uColor, vA * smoothstep(0.5, 0.0, d));
        }`,
    }));
    atmo.add(dust);
    this.dust = dust;
  }

  buildComposer() {
    const c = new EffectComposer(this.renderer);
    c.addPass(new RenderPass(this.scene, this.camera));
    const bloom = new UnrealBloomPass(new THREE.Vector2(1, 1), 0.26, 0.5, 0.96);
    c.addPass(bloom);
    c.addPass(new OutputPass());
    this.composer = c;
    this.bloom = bloom;
  }

  /* ── camera choreography ───────────────────────────────────────────── */
  setShot({ radius, theta, phi, target }) {
    this.to.s.set(radius, phi, theta);
    if (target) this.to.t.set(target[0], target[1], target[2]);
  }

  resize() {
    const w = innerWidth;
    const h = innerHeight;
    this.camera.aspect = w / h;
    /* keep the product framed on portrait screens by widening the lens */
    this.camera.fov = h > w ? 42 : 34;
    this.camera.updateProjectionMatrix();
    this.renderer.setPixelRatio(Math.min(devicePixelRatio, this.q.dpr[1]));
    this.renderer.setSize(w, h, false);
    if (this.composer) this.composer.setSize(w, h);
    if (this.dust) this.dust.material.uniforms.uPR.value = Math.min(devicePixelRatio, this.q.dpr[1]);
  }

  start() {
    if (this.running) return;
    this.running = true;
    this.clock.getDelta();
    const loop = () => {
      if (!this.running) return;
      this.frame();
      this._raf = requestAnimationFrame(loop);
    };
    this._raf = requestAnimationFrame(loop);
  }

  stop() { this.running = false; cancelAnimationFrame(this._raf); }

  setVisible(v) { this.content.visible = v; }

  frame() {
    const dt = Math.min(this.clock.getDelta(), 0.05);
    this.dt = dt;
    const t = this.clock.elapsedTime;
    const k = this.reduced ? 1 : 1 - Math.pow(0.0016, dt);   // frame-rate independent lerp

    this.from.s.radius += (this.to.s.radius - this.from.s.radius) * k;
    this.from.s.phi += (this.to.s.phi - this.from.s.phi) * k;
    this.from.s.theta += (this.to.s.theta - this.from.s.theta) * k;
    this.camTarget.lerp(this.to.t, k);

    this._v.setFromSpherical(this.from.s).add(this.camTarget);
    this.camera.position.copy(this._v);
    this.camLook.lerp(this.camTarget, Math.min(k * 1.35, 1));
    this.camera.lookAt(this.camLook);

    if (this.frameOffset.lengthSq() > 1e-8) {
      this._r.setFromMatrixColumn(this.camera.matrixWorld, 0);
      this._u.setFromMatrixColumn(this.camera.matrixWorld, 1);
      this.content.position.copy(this._r).multiplyScalar(this.frameOffset.x)
        .addScaledVector(this._u, this.frameOffset.y);
    }

    this.atmoDim += (this.atmoTarget - this.atmoDim) * Math.min(k * 2, 1);
    this.rings.forEach((r) => { r.material.opacity = r.userData.base * this.atmoDim; });
    this.floor.material.uniforms.uOpacity.value = 0.34 * this.atmoDim;

    if (!this.reduced) {
      this.rings.forEach((r, i) => {
        r.rotation.z += dt * (0.055 + i * 0.032) * (i % 2 ? -1 : 1);
        r.rotation.y += dt * 0.02 * (i % 2 ? -1 : 1);
      });
      this.dust.material.uniforms.uTime.value = t;
    }

    this.renderer.info.autoReset = false;
    this.renderer.info.reset();
    if (this.composer) this.composer.render(dt);
    else this.renderer.render(this.scene, this.camera);
    this.tris = this.renderer.info.render.triangles;

    this._frames++;
    this._fpsT += dt;
    if (this._fpsT >= 0.5) {
      this.fps = Math.round(this._frames / this._fpsT);
      this._frames = 0; this._fpsT = 0;
    }
  }

  dispose() {
    this.stop();
    this.envRT?.dispose();
    this.renderer.dispose();
  }
}