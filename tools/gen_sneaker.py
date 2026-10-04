"""
AIR MAX PHANTOM - procedural sneaker generator.
Builds an original athletic runner from lofted cross-sections, then exports a
web-ready GLB with named, recolorable materials and generated PBR textures.

Run:
  Blender.app/Contents/MacOS/Blender -b --factory-startup -P gen_sneaker.py -- --out ../assets/models
"""

import bpy
import bmesh
import math
import os
import sys
import bisect
import numpy as np
import mathutils
from mathutils import Matrix, Vector

# ----------------------------------------------------------------------------
# args
# ----------------------------------------------------------------------------
argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
OUT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "assets", "models"))
i = 0
while i < len(argv):
    if argv[i] == "--out" and i + 1 < len(argv):
        OUT_DIR = os.path.abspath(argv[i + 1])
        i += 2
    else:
        i += 1
TEX_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "source", "textures")
PREVIEW = "--preview" in argv
LENGTH = 2.60          # shoe length in build units (toe x=-1.30 .. heel x=+1.30)

os.makedirs(OUT_DIR, exist_ok=True)
os.makedirs(TEX_DIR, exist_ok=True)

# ----------------------------------------------------------------------------
# scene reset
# ----------------------------------------------------------------------------
bpy.ops.wm.read_factory_settings(use_empty=True)
SC = bpy.context.scene

PRODUCT = bpy.data.collections.new("PRODUCT")
SC.collection.children.link(PRODUCT)
STUDIO = bpy.data.collections.new("STUDIO")
SC.collection.children.link(STUDIO)


def link(obj, coll):
    for c in obj.users_collection:
        c.objects.unlink(obj)
    coll.objects.link(obj)


# ----------------------------------------------------------------------------
# monotone cubic interpolation (no overshoot - critical for silhouette work)
# ----------------------------------------------------------------------------
class Pchip:
    def __init__(self, pts):
        pts = sorted(pts, key=lambda p: p[0])
        self.x = [p[0] for p in pts]
        self.y = [p[1] for p in pts]
        n = len(pts)
        h = [self.x[i + 1] - self.x[i] for i in range(n - 1)]
        d = [(self.y[i + 1] - self.y[i]) / h[i] for i in range(n - 1)]
        m = [0.0] * n
        m[0], m[-1] = d[0], d[-1]
        for i in range(1, n - 1):
            if d[i - 1] * d[i] <= 0.0:
                m[i] = 0.0
            else:
                w1, w2 = 2 * h[i] + h[i - 1], h[i] + 2 * h[i - 1]
                m[i] = (w1 + w2) / (w1 / d[i - 1] + w2 / d[i])
        self.m, self.h = m, h

    def __call__(self, x):
        n = len(self.x)
        if x <= self.x[0]:
            return self.y[0] + self.m[0] * (x - self.x[0])
        if x >= self.x[-1]:
            return self.y[-1] + self.m[-1] * (x - self.x[-1])
        i = bisect.bisect_right(self.x, x) - 1
        h = self.h[i]
        t = (x - self.x[i]) / h
        t2, t3 = t * t, t * t * t
        return ((2 * t3 - 3 * t2 + 1) * self.y[i] + (t3 - 2 * t2 + t) * h * self.m[i]
                + (-2 * t3 + 3 * t2) * self.y[i + 1] + (t3 - t2) * h * self.m[i + 1])


# ----------------------------------------------------------------------------
# cross section outlines
# ----------------------------------------------------------------------------
def superellipse(hw, zb, zt, n_top, n_bot, samples=720):
    """Closed superellipse outline in (y,z). Boxy top/bottom exponents differ so
    the sole reads flat and the upper reads domed from one profile."""
    zc, hh = 0.5 * (zb + zt), 0.5 * (zt - zb)
    out = []
    for k in range(samples):
        a = 2.0 * math.pi * k / samples
        ca, sa = math.cos(a), math.sin(a)
        e = n_top if sa >= 0 else n_bot
        y = hw * math.copysign(abs(ca) ** (2.0 / e), ca)
        z = zc + hh * math.copysign(abs(sa) ** (2.0 / e), sa)
        out.append((y, z))
    return out


def arc_resample(poly, n):
    """Uniform arc-length resampling of a closed loop -> even point density,
    which is what keeps smooth shading clean on a low-density loft."""
    m = len(poly)
    seg = []
    total = 0.0
    for i in range(m):
        a, b = poly[i], poly[(i + 1) % m]
        d = math.hypot(b[0] - a[0], b[1] - a[1])
        seg.append(d)
        total += d
    if total <= 1e-9:
        return [poly[0]] * n
    step = total / n
    out = []
    acc, i = 0.0, 0
    run = 0.0
    for k in range(n):
        target = k * step
        while i < m - 1 and run + seg[i] < target:
            run += seg[i]
            i += 1
        a, b = poly[i], poly[(i + 1) % m]
        t = 0.0 if seg[i] < 1e-12 else (target - run) / seg[i]
        out.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
    _ = acc
    return out


# ----------------------------------------------------------------------------
# loft builder
# ----------------------------------------------------------------------------
def build_loft(name, x0, x1, nsta, npts, profile_fn, cap_start=True, cap_end=True,
               keep_face=None, uv_scale=(8.0, 6.5)):
    """profile_fn(x) -> (hw, zb, zt, n_top, n_bot) or None to skip a station.

    Emits cylindrical UVs (u wraps the cross-section, v runs along the shoe) so
    every procedural texture has something to tile against."""
    verts, faces, rings = [], [], []
    fuv = []
    uu_, vv_ = uv_scale
    for i in range(nsta):
        x = x0 + (x1 - x0) * i / (nsta - 1)
        pr = profile_fn(x)
        if pr is None:
            rings.append(None)
            continue
        hw, zb, zt, nt, nb = pr
        ring = arc_resample(superellipse(hw, zb, zt, nt, nb), npts)
        base = len(verts)
        for (y, z) in ring:
            verts.append((x, y, z))
        rings.append(base)

    for i in range(nsta - 1):
        a, b = rings[i], rings[i + 1]
        if a is None or b is None:
            continue
        v0 = i / (nsta - 1) * vv_
        v1 = (i + 1) / (nsta - 1) * vv_
        for k in range(npts):
            k2 = (k + 1) % npts
            f = (a + k, a + k2, b + k2, b + k)
            if keep_face is None or keep_face(verts[f[0]], verts[f[1]], verts[f[2]], verts[f[3]]):
                faces.append(f)
                u0 = k / npts * uu_
                u1 = (k + 1) / npts * uu_
                fuv.append(((u0, v0), (u1, v0), (u1, v1), (u0, v1)))

    if cap_start:
        i = next((j for j in range(nsta) if rings[j] is not None), None)
        if i is not None:
            base = rings[i]
            cy = sum(verts[base + k][1] for k in range(npts)) / npts
            cz = sum(verts[base + k][2] for k in range(npts)) / npts
            ci = len(verts)
            verts.append((x0 + (x1 - x0) * i / (nsta - 1), cy, cz))
            vc = i / (nsta - 1) * vv_
            for k in range(npts):
                faces.append((ci, base + (k + 1) % npts, base + k))
                fuv.append(((((k + 1) / npts) * uu_, vc), ((k / npts) * uu_, vc),
                            (((k + 0.5) / npts) * uu_, vc + 0.35)))
    if cap_end:
        j = next((jj for jj in range(nsta - 1, -1, -1) if rings[jj] is not None), None)
        if j is not None:
            base = rings[j]
            cy = sum(verts[base + k][1] for k in range(npts)) / npts
            cz = sum(verts[base + k][2] for k in range(npts)) / npts
            ci = len(verts)
            verts.append((x0 + (x1 - x0) * j / (nsta - 1), cy, cz))
            vc = j / (nsta - 1) * vv_
            for k in range(npts):
                faces.append((ci, base + k, base + (k + 1) % npts))
                fuv.append((((k / npts) * uu_, vc), (((k + 0.5) / npts) * uu_, vc + 0.35),
                            (((k + 1) / npts) * uu_, vc)))

    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], faces)
    me.validate(verbose=False)
    me.update()
    if len(fuv) == len(me.polygons):
        lay = me.uv_layers.new(name="UVMap")
        for pi, poly in enumerate(me.polygons):
            for li, co in zip(poly.loop_indices, fuv[pi]):
                lay.data[li].uv = co
    bm = bmesh.new()
    bm.from_mesh(me)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    bm.to_mesh(me)
    bm.free()
    obj = bpy.data.objects.new(name, me)
    PRODUCT.objects.link(obj)
    return obj


def smart_uv(obj, angle=math.radians(66), margin=0.004):
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.smart_project(angle_limit=angle, island_margin=margin)
    bpy.ops.object.mode_set(mode="OBJECT")


def smooth(obj, angle=math.radians(180)):
    for p in obj.data.polygons:
        p.use_smooth = True
    _ = angle


def apply_mods(obj):
    bpy.context.view_layer.objects.active = obj
    _debug_mods = obj.modifiers
    for o in bpy.context.selected_objects:
        o.select_set(False)
    obj.select_set(True)
    for m in list(obj.modifiers):
        try:
            bpy.ops.object.modifier_apply(modifier=m.name)
        except RuntimeError:
            obj.modifiers.remove(m)


def stats(tag, obj):
    bb = [Vector(c) for c in obj.bound_box]
    lo = Vector((min(v.x for v in bb), min(v.y for v in bb), min(v.z for v in bb)))
    hi = Vector((max(v.x for v in bb), max(v.y for v in bb), max(v.z for v in bb)))
    print("STAT %-16s v=%-6d f=%-6d lo=(%.3f,%.3f,%.3f) hi=(%.3f,%.3f,%.3f)"
          % (tag, len(obj.data.vertices), len(obj.data.polygons),
             lo.x, lo.y, lo.z, hi.x, hi.y, hi.z))


def boolean(target, cutter, op="DIFFERENCE"):
    """EXACT solver with a self-healing fallback: a failed exact solve that wipes
    the mesh is worse than no cut at all, so verify and retry."""
    backup = target.data.copy()
    for solver in ("EXACT", "FLOAT", "FAST"):
        target.data = backup.copy()
        m = target.modifiers.new("bool", "BOOLEAN")
        m.operation = op
        m.object = cutter
        try:
            m.solver = solver
        except TypeError:
            continue
        try:
            m.material_mode = "TRANSFER"
        except (AttributeError, TypeError):
            pass
        try:
            apply_mods(target)
        except RuntimeError:
            pass
        if len(target.data.vertices) > 0:
            print("BOOL ok   %-14s via %-6s v=%d" % (target.name, solver,
                                                    len(target.data.vertices)))
            return
        print("BOOL EMPTY %-14s via %s - falling back" % (target.name, solver))
    target.data = backup
    print("BOOL SKIPPED", target.name)


def clean_loose(obj):
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    loose = [v for v in bm.verts if not v.link_faces]
    bmesh.ops.delete(bm, geom=loose, context="VERTS")
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    bm.to_mesh(obj.data)
    bm.free()


# ----------------------------------------------------------------------------
# procedural PBR textures
# ----------------------------------------------------------------------------
def tileable_noise(size, freq, seed):
    rng = np.random.default_rng(seed)
    g = rng.random((freq, freq))
    lin = np.linspace(0.0, freq, size, endpoint=False)
    uu, vv = np.meshgrid(lin, lin)
    x0 = np.floor(uu).astype(int) % freq
    y0 = np.floor(vv).astype(int) % freq
    x1 = (x0 + 1) % freq
    y1 = (y0 + 1) % freq
    fx, fy = uu - np.floor(uu), vv - np.floor(vv)
    sx, sy = fx * fx * (3 - 2 * fx), fy * fy * (3 - 2 * fy)
    a, b = g[x0, y0], g[x1, y0]
    c, d = g[x0, y1], g[x1, y1]
    return (a * (1 - sx) + b * sx) * (1 - sy) + (c * (1 - sx) + d * sx) * sy


def fbm(size, base, octaves, seed, gain=0.5):
    out = np.zeros((size, size), dtype=np.float64)
    amp, tot, f = 1.0, 0.0, base
    for o in range(octaves):
        out += amp * tileable_noise(size, int(f), seed + o * 977)
        tot += amp
        amp *= gain
        f *= 2
    return out / tot


def height_to_normal(h, strength):
    dx = np.roll(h, -1, axis=1) - np.roll(h, 1, axis=1)
    dy = np.roll(h, -1, axis=0) - np.roll(h, 1, axis=0)
    n = np.stack([-dx * strength, -dy * strength, np.ones_like(h)], axis=-1)
    n /= np.linalg.norm(n, axis=-1, keepdims=True)
    return np.clip(n * 0.5 + 0.5, 0.0, 1.0)


def save_image(name, rgb, size):
    """rgb: float (size,size,3) in 0..1 -> PNG on disk + datablock."""
    rgba = np.ones((size, size, 4), dtype=np.float32)
    rgba[..., :3] = rgb
    path = os.path.join(TEX_DIR, name)
    img = bpy.data.images.new(name, size, size, alpha=True, float_buffer=False)
    img.pixels.foreach_set(rgba.reshape(-1))
    img.file_format = "PNG"
    img.filepath_raw = path
    img.save()
    img.pack()
    return img


def make_textures(S=256):
    lin = np.linspace(0.0, 1.0, S, endpoint=False)
    uu, vv = np.meshgrid(lin, lin)

    # --- engineered knit upper: interlocked loops + fuzz -------------------
    N = 26
    x = uu * N
    y = vv * N
    fy = y - np.floor(y)
    col = np.floor(x)
    stagger = (col % 2) * 0.5
    fyc = (y + stagger) % 1.0
    loop = np.sin(np.pi * fy) ** 1.5 * np.sin(np.pi * fyc) ** 0.6
    rib = 0.5 + 0.5 * np.cos(2 * np.pi * (x + 0.18 * np.sin(2 * np.pi * y)))
    fuzz = fbm(S, 64, 3, 11)
    knit = 0.55 * loop + 0.30 * rib + 0.15 * fuzz
    save_image("knit_normal.png", height_to_normal(knit, 26.0), S)

    # --- tongue knit: chunkier rib ----------------------------------------
    M = 14
    rib2 = 0.5 + 0.5 * np.cos(2 * np.pi * uu * M)
    row2 = 0.5 + 0.5 * np.cos(2 * np.pi * (vv * M * 1.6 + 0.25 * np.sin(2 * np.pi * uu * M)))
    knit2 = 0.62 * rib2 + 0.24 * row2 + 0.14 * fbm(S, 48, 3, 23)
    save_image("tongue_normal.png", height_to_normal(knit2, 34.0), S)

    # --- lace weave: tight diagonal ---------------------------------------
    d = np.sin(2 * np.pi * (uu * 34 + vv * 34)) * np.sin(2 * np.pi * (uu * 34 - vv * 34))
    lace = 0.5 + 0.5 * d
    lace = 0.75 * lace + 0.25 * fbm(S, 72, 2, 31)
    save_image("lace_normal.png", height_to_normal(lace, 30.0), S)

    # --- foam midsole: closed-cell speckle --------------------------------
    cells = fbm(S, 20, 3, 41)
    fine = fbm(S, 90, 2, 53)
    foam = 0.55 * cells + 0.30 * fine + 0.15 * (0.5 + 0.5 * np.cos(2 * np.pi * uu * 8))
    save_image("foam_normal.png", height_to_normal(foam, 15.0), S)

    # --- TPU / suede grain roughness --------------------------------------
    grain = fbm(S, 70, 4, 67)
    save_image("suede_rough.png", np.repeat((0.42 + 0.42 * grain)[..., None], 3, axis=2), S)

    # --- rubber roughness --------------------------------------------------
    mot = fbm(S, 26, 3, 83)
    save_image("rubber_rough.png", np.repeat((0.55 + 0.30 * mot)[..., None], 3, axis=2), S)


TEX = {}


def load_texs():
    global TEX
    TEX = {}
    for key, fname in (("knit_normal", "knit_normal.png"), ("tongue_normal", "tongue_normal.png"),
                       ("lace_normal", "lace_normal.png"), ("foam_normal", "foam_normal.png"),
                       ("suede_rough", "suede_rough.png"), ("rubber_rough", "rubber_rough.png")):
        img = bpy.data.images.load(os.path.join(TEX_DIR, fname), check_existing=True)
        TEX[key] = img


# ----------------------------------------------------------------------------
# materials
# ----------------------------------------------------------------------------
def sock(node, key, value):
    if key in node.inputs:
        node.inputs[key].default_value = value


def make_mat(name, base, rough=0.7, metal=0.0, sheen=0.0, coat=0.0,
             transmission=0.0, ior=1.45, alpha=1.0, normal_tex=None, rough_tex=None,
             normal_scale=1.0):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")
    sock(bsdf, "Base Color", (base[0], base[1], base[2], 1.0))
    sock(bsdf, "Roughness", rough)
    sock(bsdf, "Metallic", metal)
    sock(bsdf, "Sheen Weight", sheen)
    sock(bsdf, "Sheen Roughness", 0.35)
    sock(bsdf, "Coat Weight", coat)
    sock(bsdf, "Coat Roughness", 0.22)
    sock(bsdf, "Transmission Weight", transmission)
    sock(bsdf, "IOR", ior)
    sock(bsdf, "Alpha", alpha)
    if alpha < 1.0 or transmission > 0.0:
        mat.blend_method = "BLEND"
    if normal_tex:
        tn = nt.nodes.new("ShaderNodeTexImage")
        tn.image = TEX[normal_tex]
        tn.extension = "REPEAT"
        tn.location = (-700, -320)
        nmap = nt.nodes.new("ShaderNodeNormalMap")
        nmap.space = "TANGENT"
        nmap.inputs["Strength"].default_value = normal_scale
        nmap.location = (-380, -320)
        nt.links.new(tn.outputs["Color"], nmap.inputs["Color"])
        nt.links.new(nmap.outputs["Normal"], bsdf.inputs["Normal"])
    if rough_tex:
        tr = nt.nodes.new("ShaderNodeTexImage")
        tr.image = TEX[rough_tex]
        tr.extension = "REPEAT"
        tr.location = (-700, 120)
        nt.links.new(tr.outputs["Color"], bsdf.inputs["Roughness"])
    return mat


MATS = {}


def build_materials():
    MATS["MAT_Upper"] = make_mat("MAT_Upper", (0.88, 0.86, 0.81), rough=0.86, sheen=0.35,
                                 normal_tex="knit_normal", normal_scale=1.45)
    MATS["MAT_Tongue"] = make_mat("MAT_Tongue", (0.82, 0.80, 0.75), rough=0.90, sheen=0.25,
                                  normal_tex="tongue_normal", normal_scale=1.35)
    MATS["MAT_Overlay"] = make_mat("MAT_Overlay", (0.09, 0.09, 0.10), rough=0.42, coat=0.35,
                                   rough_tex="suede_rough")
    MATS["MAT_Lining"] = make_mat("MAT_Lining", (0.07, 0.07, 0.08), rough=0.95, sheen=0.5,
                                  normal_tex="knit_normal", normal_scale=1.25)
    MATS["MAT_Midsole"] = make_mat("MAT_Midsole", (0.93, 0.92, 0.89), rough=0.80,
                                   normal_tex="foam_normal", normal_scale=0.85)
    MATS["MAT_Outsole"] = make_mat("MAT_Outsole", (0.11, 0.11, 0.12), rough=0.88,
                                   normal_tex="foam_normal", normal_scale=0.9,
                                   rough_tex="rubber_rough")
    MATS["MAT_Air"] = make_mat("MAT_Air", (0.66, 0.83, 0.97), rough=0.06, transmission=0.62,
                               ior=1.30, coat=0.7)
    MATS["MAT_Lace"] = make_mat("MAT_Lace", (0.95, 0.94, 0.91), rough=0.88, sheen=0.4,
                                normal_tex="lace_normal", normal_scale=1.0)
    MATS["MAT_Accent"] = make_mat("MAT_Accent", (0.80, 1.00, 0.06), rough=0.38, coat=0.5,
                                  rough_tex="suede_rough")
    MATS["MAT_Eyelet"] = make_mat("MAT_Eyelet", (0.72, 0.73, 0.75), rough=0.28, metal=0.95)
    MATS["MAT_Collar"] = make_mat("MAT_Collar", (0.10, 0.10, 0.11), rough=0.95, sheen=0.55,
                                  normal_tex="knit_normal", normal_scale=1.5)
    MATS["MAT_Logo"] = make_mat("MAT_Logo", (0.95, 0.95, 0.94), rough=0.35, coat=0.4)
    MATS["MAT_Cavity"] = make_mat("MAT_Cavity", (0.05, 0.05, 0.06), rough=0.95)
    for m in MATS.values():
        PRODUCT_holder = m
        _ = PRODUCT_holder


def assign(obj, mat):
    obj.data.materials.clear()
    obj.data.materials.append(mat)


# ----------------------------------------------------------------------------
# silhouette definition  (x: -1.30 toe .. +1.30 heel)
# ----------------------------------------------------------------------------
# ground contact line: strong toe spring at the front, crisp bevel at the heel
GROUND = Pchip([(-1.300, 0.242), (-1.238, 0.186), (-1.152, 0.116), (-1.052, 0.056),
                (-0.960, 0.018), (-0.870, 0.001), (-0.640, 0.000), (0.240, 0.000),
                (0.700, 0.000), (0.876, 0.004), (0.984, 0.026), (1.084, 0.082),
                (1.182, 0.158), (1.252, 0.232), (1.300, 0.288)])

HALF_OUT = Pchip([(-1.300, 0.052), (-1.250, 0.140), (-1.164, 0.220), (-1.040, 0.302),
                  (-0.888, 0.370), (-0.706, 0.424), (-0.486, 0.458), (-0.246, 0.472),
                  (0.015, 0.468), (0.275, 0.444), (0.530, 0.420), (0.766, 0.416),
                  (0.940, 0.406), (1.085, 0.374), (1.206, 0.280), (1.300, 0.050)])

MID_TOP = Pchip([(-1.300, 0.322), (-1.235, 0.312), (-1.120, 0.298), (-0.960, 0.286),
                 (-0.760, 0.278), (-0.520, 0.276), (-0.260, 0.282), (0.000, 0.296),
                 (0.260, 0.320), (0.520, 0.350), (0.760, 0.380), (0.960, 0.398),
                 (1.120, 0.390), (1.230, 0.364), (1.300, 0.336)])

UPPER_TOP = Pchip([(-1.300, 0.398), (-1.245, 0.416), (-1.150, 0.442), (-1.020, 0.474),
                   (-0.860, 0.514), (-0.660, 0.562), (-0.440, 0.616), (-0.220, 0.674),
                   (0.000, 0.734), (0.200, 0.798), (0.380, 0.874), (0.540, 0.958),
                   (0.700, 1.036), (0.840, 1.082), (0.960, 1.094), (1.070, 1.070),
                   (1.170, 1.002), (1.250, 0.898), (1.300, 0.812)])

HALF_UP = Pchip([(-1.300, 0.048), (-1.252, 0.128), (-1.168, 0.204), (-1.048, 0.284),
                 (-0.898, 0.352), (-0.716, 0.406), (-0.496, 0.440), (-0.256, 0.454),
                 (0.005, 0.450), (0.265, 0.426), (0.520, 0.402), (0.756, 0.398),
                 (0.930, 0.388), (1.075, 0.356), (1.196, 0.266), (1.300, 0.048)])

THROAT_HW = Pchip([(-0.760, 0.022), (-0.640, 0.052), (-0.480, 0.076), (-0.300, 0.096),
                   (-0.110, 0.112), (0.080, 0.124), (0.250, 0.128), (0.420, 0.118),
                   (0.580, 0.092), (0.720, 0.052), (0.820, 0.018)])

CAV_HW = Pchip([(0.230, 0.030), (0.350, 0.116), (0.470, 0.168), (0.600, 0.196),
                (0.740, 0.198), (0.870, 0.178), (0.980, 0.138), (1.055, 0.082),
                (1.100, 0.030)])
CAV_BOT = Pchip([(0.230, 0.792), (0.350, 0.852), (0.500, 0.902), (0.700, 0.934),
                 (0.900, 0.930), (1.030, 0.906), (1.100, 0.872)])

OUT_T = Pchip([(-1.300, 0.072), (-1.100, 0.082), (-0.700, 0.088), (-0.200, 0.094),
               (0.300, 0.100), (0.800, 0.108), (1.300, 0.106)])


def p_outsole(x):
    return (HALF_OUT(x), GROUND(x) - 0.010, GROUND(x) + OUT_T(x), 5.0, 9.0)


def p_midsole(x):
    flare = 1.0 + 0.040 * Pchip([(-1.3, 0.0), (-0.4, 0.15), (0.4, 0.85), (1.3, 1.0)])(x)
    return (HALF_OUT(x) * flare + 0.008, GROUND(x) - 0.030, MID_TOP(x), 5.5, 11.0)


def p_upper(x):
    return (HALF_UP(x), MID_TOP(x) - 0.055, UPPER_TOP(x), 2.7, 5.5)


def p_throat(x):
    if x < -0.780 or x > 0.840:
        return None
    return (THROAT_HW(x), MID_TOP(x) - 0.010, UPPER_TOP(x) + 0.34, 3.2, 6.0)


def p_cavity(x):
    if x < 0.200 or x > 1.130:
        return None
    hw = max(0.030, CAV_HW(x))
    return (hw, CAV_BOT(x), UPPER_TOP(x) + 0.40, 2.6, 3.2)


def p_tongue(x):
    """Thin padded tongue that follows the instep and sits inside the throat."""
    if x < -0.800 or x > 0.520:
        return None
    hw = max(0.010, THROAT_HW(x) * 0.86)
    zt = UPPER_TOP(x) - 0.048
    zb = UPPER_TOP(x) - 0.130
    return (hw, zb, zt, 3.4, 7.0)


def p_air(x):
    if x < 0.560 or x > 1.245:
        return None
    flare = 1.0 + 0.040 * Pchip([(-1.3, 0.0), (-0.4, 0.15), (0.4, 0.85), (1.3, 1.0)])(x)
    hw = HALF_OUT(x) * flare * 0.72
    zt = MID_TOP(x) - 0.030
    zb = max(GROUND(x) + 0.070, MID_TOP(x) - 0.185)
    return (hw, zb, zt, 2.4, 2.8)


def p_window(x):
    if x < 0.620 or x > 1.200:
        return None
    flare = 1.0 + 0.040 * Pchip([(-1.3, 0.0), (-0.4, 0.15), (0.4, 0.85), (1.3, 1.0)])(x)
    hw = HALF_OUT(x) * flare + 0.034
    return (hw, MID_TOP(x) - 0.160, MID_TOP(x) - 0.038, 5.0, 8.0)


# ----------------------------------------------------------------------------
# build parts
# ----------------------------------------------------------------------------
def build():
    make_textures()
    load_texs()
    build_materials()

    # ---- outsole ---------------------------------------------------------
    outsole = build_loft("UNIT_OUTSOLE", -1.300, 1.300, 96, 40, p_outsole,
                         uv_scale=(9.0, 7.0))
    smooth(outsole)
    assign(outsole, MATS["MAT_Outsole"])

    # ---- midsole ---------------------------------------------------------
    midsole = build_loft("UNIT_MIDSOLE", -1.300, 1.300, 92, 42, p_midsole,
                         uv_scale=(10.0, 8.0))
    smooth(midsole)
    assign(midsole, MATS["MAT_Midsole"])

    # ---- air unit --------------------------------------------------------
    air = build_loft("UNIT_AIR", 0.540, 1.255, 36, 28, p_air, uv_scale=(4.0, 3.0))
    smooth(air)
    assign(air, MATS["MAT_Air"])

    # window cut in the midsole sidewall so the air unit reads through it
    window = build_loft("_cut_window", 0.600, 1.210, 36, 28, p_window)
    assign(window, MATS["MAT_Midsole"])
    boolean(midsole, window)
    bpy.data.objects.remove(window, do_unlink=True)

    # ---- outsole tread lugs ---------------------------------------------
    tread = build_tread()
    smart_uv(tread)
    bpy.ops.object.select_all(action="DESELECT")
    for o in (outsole, tread):
        o.select_set(True)
    bpy.context.view_layer.objects.active = outsole
    bpy.ops.object.join()
    outsole = bpy.context.view_layer.objects.active
    outsole.name = "UNIT_OUTSOLE"
    assign(outsole, MATS["MAT_Outsole"])

    # ---- upper -----------------------------------------------------------
    upper = build_loft("UPPER_MAIN", -1.300, 1.300, 108, 44, p_upper,
                       uv_scale=(7.0, 6.0))
    smooth(upper)
    assign(upper, MATS["MAT_Upper"])
    cav = build_loft("_cut_cavity", 0.200, 1.130, 46, 34, p_cavity)
    assign(cav, MATS["MAT_Lining"])
    boolean(upper, cav)
    bpy.data.objects.remove(cav, do_unlink=True)

    throat = build_loft("_cut_throat", -0.780, 0.840, 58, 26, p_throat)
    assign(throat, MATS["MAT_Lining"])
    boolean(upper, throat)
    bpy.data.objects.remove(throat, do_unlink=True)

    # ---- tongue ----------------------------------------------------------
    tongue = build_loft("UPPER_TONGUE", -0.800, 0.540, 52, 26, p_tongue,
                        uv_scale=(6.0, 5.0))
    smooth(tongue)
    assign(tongue, MATS["MAT_Tongue"])

    # ---- overlays: heel counter + toe cap -------------------------------
    # heel clip: a shell hugging the upper, trimmed to a diagonal sweep so its
    # leading edge reads as one clean line instead of a staircase
    def above_sole(v0, v1, v2, v3):
        cx = sum(q[0] for q in (v0, v1, v2, v3)) / 4.0
        cz = sum(q[2] for q in (v0, v1, v2, v3)) / 4.0
        return cz > MID_TOP(cx) + 0.014

    heel = build_loft("OVERLAY_HEEL", 0.150, 1.298, 104, 72, p_upper,
                      cap_start=False, cap_end=False, keep_face=above_sole,
                      uv_scale=(5.0, 4.0))
    inflate(heel, 1.020, 0.010)
    clean_loose(heel)
    solid(heel, 0.016)
    clip_halfspace(heel, (0.300, MID_TOP(0.300) + 0.014),
                         (0.800, MID_TOP(0.800) + 0.285), keep_positive_x=True)
    clean_loose(heel)
    bev = heel.modifiers.new("bev", "BEVEL")
    bev.width = 0.007
    bev.segments = 2
    bev.limit_method = "ANGLE"
    bev.angle_limit = math.radians(40)
    apply_mods(heel)
    smart_uv(heel)
    smooth(heel)
    assign(heel, MATS["MAT_Overlay"])

    toe = build_loft("OVERLAY_TOE", -1.298, -0.760, 68, 72, p_upper,
                     cap_start=False, cap_end=False, keep_face=above_sole,
                     uv_scale=(5.0, 2.0))
    inflate(toe, 1.013, 0.007)
    clean_loose(toe)
    solid(toe, 0.013)
    clip_halfspace(toe, (-1.298, MID_TOP(-1.298) + 0.012),
                          (-0.880, MID_TOP(-0.880) + 0.132), keep_positive_x=False)
    clean_loose(toe)
    bev = toe.modifiers.new("bev", "BEVEL")
    bev.width = 0.006
    bev.segments = 2
    bev.limit_method = "ANGLE"
    bev.angle_limit = math.radians(40)
    apply_mods(toe)
    smart_uv(toe)
    smooth(toe)
    assign(toe, MATS["MAT_Overlay"])

    # ---- side blades (original graphic, shrunk onto the upper) -----------
    spine = [(-0.830, 0.336), (-0.520, 0.452), (-0.140, 0.638), (0.250, 0.812), (0.548, 0.910)]
    wide = [0.004, 0.034, 0.046, 0.036, 0.004]
    spine2 = [(-0.700, 0.288), (-0.320, 0.428), (0.090, 0.586), (0.450, 0.752)]
    thin = [0.004, 0.012, 0.014, 0.003]
    blade = ribbon("OVERLAY_BLADE", spine, wide, upper, 0.005, 1.0)
    pin = ribbon("OVERLAY_PIN", spine2, thin, upper, 0.004, 1.0)
    blade_b = ribbon("OVERLAY_BLADE_M", spine, wide, upper, 0.005, -1.0)
    pin_b = ribbon("OVERLAY_PIN_M", spine2, thin, upper, 0.004, -1.0)
    for b in (blade, blade_b):
        assign(b, MATS["MAT_Accent"])
    for q in (pin, pin_b):
        assign(q, MATS["MAT_Logo"])

    # ---- laces + eyelets -------------------------------------------------
    laces = build_laces()
    assign(laces, MATS["MAT_Lace"])
    eyelets = build_eyelets()
    assign(eyelets, MATS["MAT_Eyelet"])

    # ---- collar padding --------------------------------------------------
    collar = build_collar()
    assign(collar, MATS["MAT_Collar"])

    # ---- heel pull tab ---------------------------------------------------
    tab = build_tab()
    assign(tab, MATS["MAT_Accent"])

    # ---- branding --------------------------------------------------------
    # start the projection right against the target surface, otherwise the
    # ray misses and the type is left stranded far outside the shoe
    logo_t = build_text("LOGO_TONGUE", "NIKE PHANTOM", size=0.072,
                        center=(-0.290, 0.0, 0.400), target=tongue, axis="Z", offset=0.004)
    logo_h = build_text("LOGO_HEEL", "NIKE", size=0.062,
                        center=(0.240, 0.0, 0.250), target=heel, axis="X", offset=0.012)

    smart_uv(eyelets)

    return dict(outsole=outsole, midsole=midsole, air=air, upper=upper, tongue=tongue,
                heel=heel, toe=toe, blade=blade, pin=pin, blade_b=blade_b, pin_b=pin_b,
                laces=laces, eyelets=eyelets, collar=collar, tab=tab,
                logo_t=logo_t, logo_h=logo_h)


def clip_halfspace(target, a, b, keep_positive_x=True, big=9.0, hy=2.2):
    """Trim `target` with the half-plane defined by the line a->b in XZ.

    Cutting the shell with a boolean gives an exactly straight leading edge,
    where dropping faces one at a time quantised it into a visible staircase.
    `keep_positive_x` selects which side survives.
    """
    ax, az = a
    bx, bz = b
    ux, uz = bx - ax, bz - az
    ln = math.hypot(ux, uz) or 1.0
    ux, uz = ux / ln, uz / ln
    nx, nz = -uz, ux                       # plane normal
    if (nx > 0) != keep_positive_x:
        nx, nz = -nx, -nz

    verts = []
    for side in (0.0, -big):               # plane face, then pushed out
        for t in (-big, big):
            for y in (-hy, hy):
                verts.append((ax + ux * t + nx * side,
                              y,
                              az + uz * t + nz * side))
    # index order: (t-,y-)(t-,y+)(t+,y-)(t+,y+) for each of the two rings
    r0, r1 = 0, 4
    faces = [
        (r0 + 0, r0 + 1, r0 + 3, r0 + 2),
        (r1 + 0, r1 + 2, r1 + 3, r1 + 1),
        (r0 + 0, r0 + 2, r1 + 2, r1 + 0),
        (r0 + 1, r1 + 1, r1 + 3, r0 + 3),
        (r0 + 0, r1 + 0, r1 + 1, r0 + 1),
        (r0 + 2, r0 + 3, r1 + 3, r1 + 2),
    ]
    me = bpy.data.meshes.new("_clip")
    me.from_pydata(verts, [], faces)
    me.validate()
    me.update()
    bm = bmesh.new()
    bm.from_mesh(me)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    bm.to_mesh(me)
    bm.free()
    cut = bpy.data.objects.new("_clip", me)
    PRODUCT.objects.link(cut)
    boolean(target, cut)
    bpy.data.objects.remove(cut, do_unlink=True)


def inflate(obj, s, dz):
    for v in obj.data.vertices:
        v.co.y *= s
        v.co.z += dz * (v.co.z / max(UPPER_TOP(v.co.x), 1e-3))
    obj.data.update()


def solid(obj, t):
    m = obj.modifiers.new("solid", "SOLIDIFY")
    m.thickness = t
    m.offset = 0.0
    m.use_even_offset = False
    apply_mods(obj)


def build_tread():
    verts, faces = [], []
    gx = np.arange(-1.22, 1.24, 0.098)
    gy = np.arange(-0.55, 0.56, 0.100)
    for x in gx:
        for y in gy:
            hw = HALF_OUT(float(x))
            if hw < 0.10 or abs(y) > hw * 0.90:
                continue
            gz = GROUND(float(x))
            if gz > 0.028:
                continue
            sx, sy = 0.036, 0.038
            hh = 0.020 + 0.020 * (gz > 0.012)
            b = len(verts)
            for zz in (gz - hh, gz + 0.006):
                for (dx, dy) in ((-sx, -sy), (sx, -sy), (sx, sy), (-sx, sy)):
                    verts.append((float(x) + dx, float(y) + dy, zz))
            faces += [(b + 0, b + 3, b + 2, b + 1), (b + 4, b + 5, b + 6, b + 7),
                      (b + 0, b + 1, b + 5, b + 4), (b + 1, b + 2, b + 6, b + 5),
                      (b + 2, b + 3, b + 7, b + 6), (b + 3, b + 0, b + 4, b + 7)]
    me = bpy.data.meshes.new("TREAD")
    me.from_pydata(verts, [], faces)
    me.validate()
    me.update()
    obj = bpy.data.objects.new("UNIT_OUTSOLE_TMP", me)
    PRODUCT.objects.link(obj)
    bev = obj.modifiers.new("bev", "BEVEL")
    bev.width = 0.006
    bev.segments = 2
    apply_mods(obj)
    return obj


def ribbon(name, spine, widths, target, offset, side):
    """Flat tapered ribbon in the XZ plane, then projected onto the upper so the
    graphic hugs the shoe's actual curvature instead of floating off it."""
    ns = len(spine)
    pts = []
    nrm = []
    for i, (x, z) in enumerate(spine):
        if i == 0:
            dx, dz = spine[1][0] - x, spine[1][1] - z
        elif i == ns - 1:
            dx, dz = x - spine[-2][0], z - spine[-2][1]
        else:
            dx, dz = spine[i + 1][0] - spine[i - 1][0], spine[i + 1][1] - spine[i - 1][1]
        ln = math.hypot(dx, dz) or 1.0
        nx, nz = -dz / ln, dx / ln
        pts.append((x, z, nx, nz))
    dens = 18
    verts, faces = [], []
    rows = (ns - 1) * dens + 1
    for i, (x, z, nx, nz) in enumerate(pts):
        w = widths[i]
        seg = range(dens) if i < ns - 1 else range(dens)
        for j in range(dens):
            t = j / dens
            px = x + nx * w * (t - 0.5) * 2.0
            pz = z + nz * w * (t - 0.5) * 2.0
            seed = min(HALF_UP(px), 0.34) + 0.045
            verts.append((px, side * seed, pz))
    for i in range(ns - 1):
        for j in range(dens):
            a = i * dens + j
            b = (i + 1) * dens + j
            faces.append((a, a + 1, b + 1, b))
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], faces)
    me.validate()
    me.update()
    obj = bpy.data.objects.new(name, me)
    PRODUCT.objects.link(obj)
    bm = bmesh.new()
    bm.from_mesh(me)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    bm.to_mesh(me)
    bm.free()

    sw = obj.modifiers.new("sw", "SHRINKWRAP")
    sw.target = target
    sw.wrap_method = "NEAREST_SURFACEPOINT"
    sw.offset = offset
    sw.wrap_mode = "ON_SURFACE"
    apply_mods(obj)
    so = obj.modifiers.new("so", "SOLIDIFY")
    so.thickness = 0.010
    so.offset = 1.0
    apply_mods(obj)
    clean_loose(obj)
    smart_uv(obj)
    smooth(obj)
    _ = rows
    return obj


EYE_X = [-0.700, -0.545, -0.390, -0.235, -0.080, 0.075]


def build_laces():
    cu = bpy.data.curves.new("LACES", "CURVE")
    cu.dimensions = "3D"
    cu.bevel_depth = 0.0165
    cu.bevel_resolution = 3
    cu.resolution_u = 7

    def bez(co):
        sp = cu.splines.new("BEZIER")
        sp.bezier_points.add(len(co) - 1)
        for b, p in zip(sp.bezier_points, co):
            b.co = p
            b.handle_left_type = "AUTO"
            b.handle_right_type = "AUTO"
        return sp

    for side in (1, -1):
        for i in range(len(EYE_X) - 1):
            x0, x1 = EYE_X[i], EYE_X[i + 1]
            xm = 0.5 * (x0 + x1)
            bez([(x0, side * (THROAT_HW(x0) + 0.008), UPPER_TOP(x0) - 0.070),
                 (xm, 0.0, UPPER_TOP(xm) - 0.028),
                 (x1, side * (THROAT_HW(x1) + 0.008), UPPER_TOP(x1) - 0.070)])

    # simple two-loop bow at the top eyelet pair
    bx = EYE_X[-1]
    by = THROAT_HW(bx) + 0.010
    bz = UPPER_TOP(bx) - 0.070
    for side in (1, -1):
        bez([(bx + 0.010, side * by, bz + 0.006),
             (bx + 0.070, side * (by + 0.062), bz + 0.070),
             (bx + 0.008, side * (by + 0.070), bz + 0.104),
             (bx - 0.052, side * (by + 0.036), bz + 0.062),
             (bx + 0.010, side * by, bz + 0.006)])
        bez([(bx - 0.006, side * (by - 0.004), bz + 0.002),
             (bx - 0.070, side * (by + 0.048), bz - 0.048),
             (bx - 0.128, side * (by + 0.070), bz - 0.116)])

    ob = bpy.data.objects.new("DETAIL_LACES", cu)
    PRODUCT.objects.link(ob)
    bpy.context.view_layer.objects.active = ob
    ob.select_set(True)
    bpy.ops.object.convert(target="MESH")
    ob = bpy.context.view_layer.objects.active
    smooth(ob)
    return ob


def build_eyelets():
    verts, faces = [], []
    for x in EYE_X:
        for side in (1, -1):
            cy = side * (THROAT_HW(x) + 0.012)
            cz = UPPER_TOP(x) - 0.070
            R, r, n, m = 0.027, 0.0075, 12, 6
            base = len(verts)
            for i in range(n):
                a = 2 * math.pi * i / n
                for j in range(m):
                    b = 2 * math.pi * j / m
                    rr = R + r * math.cos(b)
                    verts.append((x + rr * math.cos(a),
                                  cy + r * math.sin(b),
                                  cz + rr * math.sin(a)))
            for i in range(n):
                i2 = (i + 1) % n
                for j in range(m):
                    j2 = (j + 1) % m
                    faces.append((base + i * m + j, base + i2 * m + j,
                                  base + i2 * m + j2, base + i * m + j2))
    me = bpy.data.meshes.new("DETAIL_EYELETS")
    me.from_pydata(verts, [], faces)
    me.validate()
    me.update()
    obj = bpy.data.objects.new("DETAIL_EYELETS", me)
    PRODUCT.objects.link(obj)
    bm = bmesh.new()
    bm.from_mesh(me)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    bm.to_mesh(me)
    bm.free()
    smooth(obj)
    return obj


def build_collar():
    cu = bpy.data.curves.new("COLLAR", "CURVE")
    cu.dimensions = "3D"
    cu.bevel_depth = 0.034
    cu.bevel_resolution = 4
    cu.resolution_u = 6
    sp = cu.splines.new("POLY")
    pts = []
    xs = np.linspace(0.250, 1.076, 44)
    for side in (1, -1):
        rng = xs if side > 0 else xs[::-1]
        for x in rng:
            y = side * (CAV_HW(float(x)) * 1.10)
            z = UPPER_TOP(float(x)) - 0.052
            pts.append((float(x), y, z))
    sp.points.add(len(pts) - 1)
    for i, p in enumerate(pts):
        sp.points[i].co = (p[0], p[1], p[2], 1.0)
    sp.use_cyclic_u = True
    ob = bpy.data.objects.new("DETAIL_COLLAR", cu)
    PRODUCT.objects.link(ob)
    bpy.context.view_layer.objects.active = ob
    ob.select_set(True)
    bpy.ops.object.convert(target="MESH")
    ob = bpy.context.view_layer.objects.active
    sm = ob.modifiers.new("sm", "SMOOTH")
    sm.factor = 0.4
    sm.iterations = 2
    apply_mods(ob)
    smooth(ob)
    return ob


def build_tab():
    cu = bpy.data.curves.new("TAB", "CURVE")
    cu.dimensions = "3D"
    cu.bevel_depth = 0.023
    cu.bevel_resolution = 3
    sp = cu.splines.new("BEZIER")
    sp.bezier_points.add(2)
    c = [(1.130, 0.0, 1.010), (1.238, 0.0, 1.120), (1.170, 0.0, 1.196)]
    for b, co in zip(sp.bezier_points, c):
        b.co = co
        b.handle_left_type = "AUTO"
        b.handle_right_type = "AUTO"
    ob = bpy.data.objects.new("DETAIL_HEELTAB", cu)
    PRODUCT.objects.link(ob)
    bpy.context.view_layer.objects.active = ob
    ob.select_set(True)
    bpy.ops.object.convert(target="MESH")
    ob = bpy.context.view_layer.objects.active
    smooth(ob)
    return ob


def build_text(name, body, size, center, target, axis, offset):
    """Type set as a mesh then shrink-wrapped onto the surface it belongs to, so
    the branding follows the shoe's curvature instead of floating above it."""
    cu = bpy.data.curves.new(name + "_c", "FONT")
    cu.body = body
    cu.align_x = "CENTER"
    cu.align_y = "CENTER"
    cu.size = size
    cu.extrude = 0.003
    cu.space_character = 1.10
    ob = bpy.data.objects.new(name, cu)
    PRODUCT.objects.link(ob)
    if axis == "X":
        right, up, nrm = Vector((0.0, -1.0, 0.0)), Vector((0.0, 0.0, 1.0)), Vector((1.0, 0.0, 0.0))
    else:
        right, up, nrm = Vector((1.0, 0.0, 0.0)), Vector((0.0, 1.0, 0.0)), Vector((0.0, 0.0, 1.0))
    m = Matrix(((right.x, up.x, nrm.x, center[0]),
                (right.y, up.y, nrm.y, center[1]),
                (right.z, up.z, nrm.z, center[2]),
                (0.0, 0.0, 0.0, 1.0)))
    ob.matrix_world = m
    bpy.context.view_layer.objects.active = ob
    ob.select_set(True)
    bpy.ops.object.convert(target="MESH")
    ob = bpy.context.view_layer.objects.active

    sw = ob.modifiers.new("sw", "SHRINKWRAP")
    sw.target = target
    sw.wrap_method = "PROJECT"
    if axis == "X":
        sw.use_project_x = True
        sw.use_negative_direction = False
        sw.use_positive_direction = True
    else:
        sw.use_project_z = True
        sw.use_negative_direction = True
        sw.use_positive_direction = False
    sw.offset = offset
    apply_mods(ob)
    clean_loose(ob)
    solid(ob, 0.005)
    smart_uv(ob)
    smooth(ob)
    assign(ob, MATS["MAT_Logo"])
    # identity transform from here on, so finalize()'s uniform scale is honest
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    return ob


# ----------------------------------------------------------------------------
# normalize scale (shoe length -> 1.0) and export
# ----------------------------------------------------------------------------
def finalize(parts):
    k = 1.0 / LENGTH
    for ob in parts.values():
        if ob is None or ob.type != "MESH":
            continue
        ob.scale = (k, k, k)
    bpy.ops.object.select_all(action="DESELECT")
    for ob in parts.values():
        if ob is None or ob.type != "MESH":
            continue
        ob.select_set(True)
        bpy.context.view_layer.objects.active = ob
        bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)


def export_glb(path):
    bpy.ops.object.select_all(action="DESELECT")
    for ob in PRODUCT.objects:
        if ob.type == "MESH":
            ob.select_set(True)
    bpy.context.view_layer.objects.active = next(o for o in PRODUCT.objects if o.type == "MESH")
    kw = dict(filepath=path, export_format="GLB", export_apply=True,
              use_selection=True, export_yup=True, export_materials="EXPORT",
              export_image_format="AUTO", export_normals=True,
              export_tangents=True)
    try:
        bpy.ops.export_scene.gltf(**kw)
    except TypeError:
        kw.pop("export_image_format", None)
        bpy.ops.export_scene.gltf(**kw)


# ----------------------------------------------------------------------------
# optional preview render
# ----------------------------------------------------------------------------
def preview(path="/tmp/phantom_preview.png"):
    """Studio turntable-ish renders used for art direction QA."""
    wld = bpy.data.worlds.new("W")
    SC.world = wld
    wld.use_nodes = True
    bg = next(n for n in wld.node_tree.nodes if n.type == "BACKGROUND")
    bg.inputs[0].default_value = (0.055, 0.058, 0.066, 1.0)
    bg.inputs[1].default_value = 0.30

    tgt = bpy.data.objects.new("TGT", None)
    tgt.location = (0.0, 0.0, 0.22)
    STUDIO.objects.link(tgt)

    cam_d = bpy.data.cameras.new("C")
    cam_d.lens = 70
    cam = bpy.data.objects.new("C", cam_d)
    STUDIO.objects.link(cam)
    tc = cam.constraints.new("TRACK_TO")
    tc.target = tgt
    tc.track_axis = "TRACK_NEGATIVE_Z"
    tc.up_axis = "UP_Y"
    SC.camera = cam

    def area(name, loc, size, power, color=(1, 1, 1), shape="SQUARE"):
        ld = bpy.data.lights.new(name, "AREA")
        ld.energy = power
        ld.size = size
        ld.shape = shape
        ld.color = color
        o = bpy.data.objects.new(name, ld)
        o.location = loc
        c = o.constraints.new("TRACK_TO")
        c.target = tgt
        c.track_axis = "TRACK_NEGATIVE_Z"
        c.up_axis = "UP_Y"
        STUDIO.objects.link(o)
        return o

    area("K", (1.5, 1.9, 1.5), 2.6, 95)
    area("F", (-1.9, 1.5, 0.7), 2.2, 50)
    area("R", (0.4, -2.2, 1.1), 2.6, 70, (0.92, 0.95, 1.0))
    area("T", (0.0, 0.3, 2.4), 3.0, 70)

    SC.render.engine = "CYCLES"
    SC.cycles.samples = 40
    SC.cycles.use_denoising = True
    SC.render.resolution_x = 880
    SC.render.resolution_y = 620
    SC.render.film_transparent = False
    SC.view_settings.view_transform = "AgX"
    SC.render.image_settings.file_format = "PNG"

    views = [
        ("side",    (0.0, -1.0, 0.30), 3.30),
        ("three_q", (-0.72, 1.0, 0.46), 3.20),
        ("medial",  (0.55, 1.35, 0.42), 3.20),
        ("top",     (0.0, 0.02, 1.0), 3.30),
        ("heel",    (-1.0, 0.60, 0.42), 3.00),
        ("front",   (1.0, -0.32, 0.34), 3.00),
    ]
    for name, loc, dist in views:
        tgt.location = (0.0, 0.0, 0.24)
        d = Vector(loc).normalized() * dist
        cam.location = d
        SC.render.filepath = "/tmp/phantom_%s.png" % name
        bpy.ops.render.render(write_still=True)
        print("VIEW", name, SC.render.filepath)


def clay():
    """Single-material read of the raw silhouettes for art-direction QA."""
    m = make_mat("CLAY", (0.62, 0.62, 0.64), rough=0.55)
    for ob in PRODUCT.objects:
        if ob.type == "MESH":
            assign(ob, m)


if __name__ == "__main__":
    parts = build()
    if "--clay" in argv:
        clay()
    finalize(parts)
    glb = os.path.join(OUT_DIR, "phantom-runner.glb")
    export_glb(glb)
    tris = 0
    for ob in PRODUCT.objects:
        if ob.type == "MESH":
            tris += sum(len(p.vertices) - 2 for p in ob.data.polygons)
    from mathutils import Vector as _V
    lo = [1e9] * 3
    hi = [-1e9] * 3
    for ob in PRODUCT.objects:
        if ob.type != "MESH":
            continue
        for c in ob.bound_box:
            w = ob.matrix_world @ _V(c)
            for i in range(3):
                lo[i] = min(lo[i], w[i])
                hi[i] = max(hi[i], w[i])
    print("BOUNDS size=(%.3f, %.3f, %.3f) lo=(%.3f, %.3f, %.3f)"
          % (hi[0] - lo[0], hi[1] - lo[1], hi[2] - lo[2], lo[0], lo[1], lo[2]))
    print("EXPORTED", glb, os.path.getsize(glb) // 1024, "KB", tris, "tris",
          len([o for o in PRODUCT.objects if o.type == "MESH"]), "objects")
    if PREVIEW:
        preview()
