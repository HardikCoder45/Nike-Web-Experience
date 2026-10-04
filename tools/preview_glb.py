"""Render the exported GLB back through the studio rig.
This is the real QA loop: it validates the file the website will actually load.
"""
import bpy
import math
import os
import sys
from mathutils import Vector

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
GLB = argv[0] if argv else os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "assets", "models", "phantom-runner.raw.glb"))
OUT = "/tmp/glb"

bpy.ops.wm.read_factory_settings(use_empty=True)
SC = bpy.context.scene
SC.collection.children.link(bpy.data.collections.new("STUDIO"))

bpy.ops.import_scene.gltf(filepath=GLB)
for ob in list(bpy.data.objects):
    if ob.type == "MESH":
        ob.scale = (1.0, 1.0, 1.0)

wld = bpy.data.worlds.new("W")
SC.world = wld
wld.use_nodes = True
bg = next(n for n in wld.node_tree.nodes if n.type == "BACKGROUND")
bg.inputs[0].default_value = (0.05, 0.055, 0.065, 1.0)
bg.inputs[1].default_value = 0.35

STUDIO = SC.collection


def area(name, loc, size, power, color=(1, 1, 1)):
    ld = bpy.data.lights.new(name, "AREA")
    ld.energy, ld.size, ld.color = power, size, color
    o = bpy.data.objects.new(name, ld)
    o.location = loc
    c = o.constraints.new("TRACK_TO")
    c.target = tgt
    c.track_axis = "TRACK_NEGATIVE_Z"
    c.up_axis = "UP_Y"
    STUDIO.objects.link(o)


tgt = bpy.data.objects.new("TGT", None)
tgt.location = (0.0, 0.0, 0.20)
STUDIO.objects.link(tgt)

cam_d = bpy.data.cameras.new("C")
cam_d.lens = 78
cam = bpy.data.objects.new("C", cam_d)
c = cam.constraints.new("TRACK_TO")
c.target, c.track_axis, c.up_axis = tgt, "TRACK_NEGATIVE_Z", "UP_Y"
STUDIO.objects.link(cam)
SC.camera = cam

area("K", (1.6, 1.9, 1.4), 2.6, 110)
area("F", (-1.9, 1.6, 0.8), 2.2, 55)
area("R", (0.4, -2.3, 1.2), 2.6, 80, (0.90, 0.94, 1.0))
area("T", (0.0, 0.3, 2.4), 3.0, 80)

SC.render.engine = "CYCLES"
SC.cycles.samples = 64
SC.cycles.use_denoising = True
SC.render.resolution_x = 960
SC.render.resolution_y = 660
SC.view_settings.view_transform = "AgX"
SC.render.image_settings.file_format = "PNG"

VIEWS = [
    ("side",    (0.0, -1.0, 0.24), 3.10),
    ("three_q", (-0.70, 1.0, 0.42), 3.00),
    ("hero",    (-0.55, -1.0, 0.30), 2.95),
    ("heel",    (-1.0, 0.62, 0.40), 2.85),
    ("top",     (0.0, 0.02, 1.0), 3.10),
    ("front",   (1.0, -0.34, 0.30), 2.85),
]
for name, loc, dist in VIEWS:
    cam.location = Vector(loc).normalized() * dist
    SC.render.filepath = os.path.join(OUT, name + ".png")
    bpy.ops.render.render(write_still=True)
    print("VIEW", SC.render.filepath)