"""
Regenerates assets/primitives.blend from scratch.

Run headless with Blender 4.1+ :

    blender --background --python scripts/build_library.py

The script is fully deterministic and idempotent: re-running it always
rebuilds the same 14 assets, re-renders their preview thumbnails and
re-marks them as Blender assets with stable catalog UUIDs (so existing
catalog assignments in blender_assets.cats.txt keep matching).
"""

import bpy
import bmesh
import colorsys
import math
import os
import mathutils

# ---------------------------------------------------------------------------
# Paths & stable catalog UUIDs (do not change once published — these are what
# links each asset to a row in blender_assets.cats.txt)
# ---------------------------------------------------------------------------

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS_DIR = os.path.join(ROOT, "assets")
BLEND_PATH = os.path.join(ASSETS_DIR, "primitives.blend")
CATS_PATH = os.path.join(ASSETS_DIR, "blender_assets.cats.txt")
THUMB_DIR = os.path.join(ASSETS_DIR, ".thumbs")

CATALOG_BASE = "6f46c395-e541-49e2-805e-6b76b228386c"
CATALOG_KIT = "7bc7ab05-58e9-42ee-821b-feea30abdfb6"

os.makedirs(ASSETS_DIR, exist_ok=True)
os.makedirs(THUMB_DIR, exist_ok=True)

# ---------------------------------------------------------------------------
# Fresh scene
# ---------------------------------------------------------------------------

bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene

world = bpy.data.worlds.new("World")
world.use_nodes = True
bg = world.node_tree.nodes["Background"]
bg.inputs[0].default_value = (0.75, 0.75, 0.75, 1.0)
bg.inputs[1].default_value = 1.4
scene.world = world

clay = bpy.data.materials.new("Library Clay")
clay.use_nodes = True
bsdf = clay.node_tree.nodes["Principled BSDF"]
bsdf.inputs["Base Color"].default_value = (0.68, 0.68, 0.7, 1.0)
bsdf.inputs["Roughness"].default_value = 0.45

# Only used to color the thumbnail renders (Blender-Asset-Browser style, one
# distinct hue per asset) — never shipped as the asset's actual material.
preview_mat = bpy.data.materials.new("Preview Color")
preview_mat.use_nodes = True
preview_bsdf = preview_mat.node_tree.nodes["Principled BSDF"]
preview_bsdf.inputs["Roughness"].default_value = 0.35

scene.render.engine = "CYCLES"
scene.cycles.samples = 64
scene.cycles.use_denoising = True
scene.render.resolution_x = 256
scene.render.resolution_y = 256
scene.render.film_transparent = True
scene.render.image_settings.file_format = "PNG"
scene.render.image_settings.color_mode = "RGBA"


def preview_color(index, total):
    """Distinct, repeatable hue per asset (golden-angle spacing)."""
    hue = (index * 0.6180339887498949 + 0.08) % 1.0
    r, g, b = colorsys.hsv_to_rgb(hue, 0.62, 0.95)
    return (r, g, b, 1.0)

cam_data = bpy.data.cameras.new("ThumbCam")
cam_data.lens = 50
cam = bpy.data.objects.new("ThumbCam", cam_data)
scene.collection.objects.link(cam)
scene.camera = cam

key_data = bpy.data.lights.new("ThumbKey", type="SUN")
key_data.energy = 3.0
key = bpy.data.objects.new("ThumbKey", key_data)
scene.collection.objects.link(key)

base_col = bpy.data.collections.new("Base")
scene.collection.children.link(base_col)
kit_col = bpy.data.collections.new("Hard Surface Kit")
scene.collection.children.link(kit_col)

# ---------------------------------------------------------------------------
# Mesh builders
# ---------------------------------------------------------------------------


def spawn_via_op(op_call):
    op_call()
    obj = bpy.context.active_object
    for c in list(obj.users_collection):
        c.objects.unlink(obj)
    return obj


def mesh_from_bmesh(bm, name):
    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()
    return bpy.data.objects.new(name, mesh)


def build_tube(name="Tube", outer_r=1.0, inner_r=0.65, depth=2.0, segments=32):
    bm = bmesh.new()
    outer_top, outer_bot, inner_top, inner_bot = [], [], [], []
    for i in range(segments):
        a = 2 * math.pi * i / segments
        x, y = math.cos(a), math.sin(a)
        outer_top.append(bm.verts.new((x * outer_r, y * outer_r, depth / 2)))
        outer_bot.append(bm.verts.new((x * outer_r, y * outer_r, -depth / 2)))
        inner_top.append(bm.verts.new((x * inner_r, y * inner_r, depth / 2)))
        inner_bot.append(bm.verts.new((x * inner_r, y * inner_r, -depth / 2)))
    bm.verts.ensure_lookup_table()
    for i in range(segments):
        j = (i + 1) % segments
        bm.faces.new((outer_bot[i], outer_bot[j], outer_top[j], outer_top[i]))
        bm.faces.new((inner_top[i], inner_top[j], inner_bot[j], inner_bot[i]))
        bm.faces.new((outer_top[i], outer_top[j], inner_top[j], inner_top[i]))
        bm.faces.new((outer_bot[j], outer_bot[i], inner_bot[i], inner_bot[j]))
    bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
    return mesh_from_bmesh(bm, name)


def build_dome(name="Dome", radius=1.0, u=32, v=16):
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=u, v_segments=v, radius=radius)
    geom = bm.verts[:] + bm.edges[:] + bm.faces[:]
    bmesh.ops.bisect_plane(
        bm, geom=geom, dist=0.0001, plane_co=(0, 0, 0), plane_no=(0, 0, 1),
        clear_inner=True, clear_outer=False,
    )
    open_edges = [e for e in bm.edges if e.is_boundary]
    bmesh.ops.edgeloop_fill(bm, edges=open_edges)
    bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
    return mesh_from_bmesh(bm, name)


def build_wedge(name="Wedge", width=2.0, depth=2.0, height=2.0):
    bm = bmesh.new()
    hw, hd = width / 2, depth / 2
    v0 = bm.verts.new((-hw, -hd, 0))
    v1 = bm.verts.new((hw, -hd, 0))
    v2 = bm.verts.new((hw, hd, 0))
    v3 = bm.verts.new((-hw, hd, 0))
    v4 = bm.verts.new((-hw, -hd, height))
    v5 = bm.verts.new((hw, -hd, height))
    bm.faces.new((v0, v1, v2, v3))
    bm.faces.new((v0, v4, v5, v1))
    bm.faces.new((v4, v3, v2, v5))
    bm.faces.new((v0, v3, v4))
    bm.faces.new((v1, v5, v2))
    bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
    return mesh_from_bmesh(bm, name)


def build_stairs(name="Stairs", steps=5, width=2.0, total_depth=2.0, total_height=2.0):
    step_depth = total_depth / steps
    step_height = total_height / steps
    hd, hw = total_depth / 2, width / 2

    # 2D staircase silhouette in the YZ plane, front-bottom to back-top.
    profile = [(-hd, 0.0)]
    for k in range(steps):
        y0 = -hd + k * step_depth
        y1 = -hd + (k + 1) * step_depth
        z1 = (k + 1) * step_height
        profile.append((y0, z1))
        profile.append((y1, z1))
    profile.append((hd, 0.0))

    bm = bmesh.new()
    side_a = [bm.verts.new((-hw, y, z)) for (y, z) in profile]
    side_b = [bm.verts.new((hw, y, z)) for (y, z) in profile]
    n = len(profile)
    for i in range(n):
        j = (i + 1) % n
        bm.faces.new((side_a[i], side_a[j], side_b[j], side_b[i]))
    bm.faces.new(side_a)
    bm.faces.new(list(reversed(side_b)))
    bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
    return mesh_from_bmesh(bm, name)


# ---------------------------------------------------------------------------
# Parametric (Geometry Nodes) primitives — real modifier inputs + native
# viewport gizmos (GeometryNodeGizmoLinear / GeometryNodeGizmoDial), so the
# shape stays fully adjustable after being dragged in from the asset browser.
# ---------------------------------------------------------------------------


def ensure_smooth_by_angle_group():
    """Make sure Blender's bundled 'Smooth by Angle' node group is loaded."""
    existing = bpy.data.node_groups.get("Smooth by Angle")
    if existing:
        return existing
    bpy.ops.mesh.primitive_plane_add()
    tmp = bpy.context.active_object
    tmp.select_set(True)
    with bpy.context.temp_override(active_object=tmp, selected_editable_objects=[tmp], object=tmp):
        bpy.ops.object.shade_auto_smooth(angle=math.radians(30))
    bpy.data.objects.remove(tmp, do_unlink=True)
    return bpy.data.node_groups["Smooth by Angle"]


def build_cube_gn_group(name="[PrimLib] Cube"):
    """Geometry Nodes group: parametric cube with Size/Division gizmos.

    Interface: Size (vector), Division X/Y/Z (int), Corner Ratio (vector,
    pivot control), Smooth (bool), Smooth Angle (float). Size is exposed as
    3 linear drag gizmos on the +X/+Y/+Z faces; Division as 3 dial gizmos
    at the same positions.
    """
    sba = ensure_smooth_by_angle_group()

    ng = bpy.data.node_groups.new(name, "GeometryNodeTree")
    iface = ng.interface

    iface.new_socket(name="Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    iface.new_socket(name="Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")

    size_in = iface.new_socket(name="Size", in_out="INPUT", socket_type="NodeSocketVector")
    size_in.default_value = (2.0, 2.0, 2.0)
    size_in.min_value = 0.001

    for axis in ("X", "Y", "Z"):
        s = iface.new_socket(name=f"Division {axis}", in_out="INPUT", socket_type="NodeSocketInt")
        s.default_value = 0
        s.min_value = 0

    corner_in = iface.new_socket(name="Corner Ratio", in_out="INPUT", socket_type="NodeSocketVector")
    corner_in.default_value = (0.0, 0.0, 0.0)
    corner_in.min_value = -1.0
    corner_in.max_value = 1.0

    smooth_in = iface.new_socket(name="Smooth", in_out="INPUT", socket_type="NodeSocketBool")
    smooth_in.default_value = False

    angle_in = iface.new_socket(name="Smooth Angle", in_out="INPUT", socket_type="NodeSocketFloat")
    angle_in.subtype = "ANGLE"
    angle_in.default_value = math.radians(30)

    mat_in = iface.new_socket(name="Material", in_out="INPUT", socket_type="NodeSocketMaterial")
    mat_in.default_value = clay

    group_in = ng.nodes.new("NodeGroupInput")
    group_in.location = (-1100, 0)
    group_out = ng.nodes.new("NodeGroupOutput")
    group_out.location = (900, 0)

    cube_node = ng.nodes.new("GeometryNodeMeshCube")
    cube_node.location = (-700, 300)
    ng.links.new(group_in.outputs["Size"], cube_node.inputs["Size"])

    for i, axis in enumerate(("X", "Y", "Z")):
        add = ng.nodes.new("ShaderNodeMath")
        add.operation = "ADD"
        add.inputs[1].default_value = 2.0
        add.location = (-1100, -150 * (i + 1))
        ng.links.new(group_in.outputs[f"Division {axis}"], add.inputs[0])
        ng.links.new(add.outputs["Value"], cube_node.inputs[f"Vertices {axis}"])

    # Pivot: offset = -(CornerRatio * Size * 0.5)
    mul1 = ng.nodes.new("ShaderNodeVectorMath")
    mul1.operation = "MULTIPLY"
    mul1.location = (-700, -600)
    ng.links.new(group_in.outputs["Corner Ratio"], mul1.inputs[0])
    ng.links.new(group_in.outputs["Size"], mul1.inputs[1])

    offset_node = ng.nodes.new("ShaderNodeVectorMath")
    offset_node.operation = "SCALE"
    offset_node.inputs["Scale"].default_value = -0.5
    offset_node.location = (-450, -600)
    ng.links.new(mul1.outputs["Vector"], offset_node.inputs["Vector"])

    transform_node = ng.nodes.new("GeometryNodeTransform")
    transform_node.location = (-300, 300)
    ng.links.new(cube_node.outputs["Mesh"], transform_node.inputs["Geometry"])
    ng.links.new(offset_node.outputs["Vector"], transform_node.inputs["Translation"])

    sba_node = ng.nodes.new("GeometryNodeGroup")
    sba_node.node_tree = sba
    sba_node.location = (0, 300)
    ng.links.new(transform_node.outputs["Geometry"], sba_node.inputs[0])
    ng.links.new(group_in.outputs["Smooth Angle"], sba_node.inputs["Angle"])

    switch_node = ng.nodes.new("GeometryNodeSwitch")
    switch_node.input_type = "GEOMETRY"
    switch_node.location = (300, 200)
    ng.links.new(group_in.outputs["Smooth"], switch_node.inputs["Switch"])
    ng.links.new(transform_node.outputs["Geometry"], switch_node.inputs[False])
    ng.links.new(sba_node.outputs[0], switch_node.inputs[True])

    set_mat_node = ng.nodes.new("GeometryNodeSetMaterial")
    set_mat_node.location = (600, 200)
    ng.links.new(switch_node.outputs[0], set_mat_node.inputs["Geometry"])
    ng.links.new(group_in.outputs["Material"], set_mat_node.inputs["Material"])
    ng.links.new(set_mat_node.outputs["Geometry"], group_out.inputs["Geometry"])

    # --- Gizmos: Size (linear drag) + Division (dial) per axis, positioned
    # at the corresponding face center (following the pivot offset).
    sep_size = ng.nodes.new("ShaderNodeSeparateXYZ")
    sep_size.location = (-700, -900)
    ng.links.new(group_in.outputs["Size"], sep_size.inputs["Vector"])

    half_axis_vecs = {}
    for i, axis in enumerate(("X", "Y", "Z")):
        combine = ng.nodes.new("ShaderNodeCombineXYZ")
        combine.location = (-450, -900 - 150 * i)
        half = ng.nodes.new("ShaderNodeMath")
        half.operation = "MULTIPLY"
        half.inputs[1].default_value = 0.5
        half.location = (-600, -900 - 150 * i)
        ng.links.new(sep_size.outputs[axis], half.inputs[0])
        ng.links.new(half.outputs["Value"], combine.inputs[axis])
        half_axis_vecs[axis] = combine

    for i, axis in enumerate(("X", "Y", "Z")):
        pos_add = ng.nodes.new("ShaderNodeVectorMath")
        pos_add.operation = "ADD"
        pos_add.location = (-200, -900 - 150 * i)
        ng.links.new(offset_node.outputs["Vector"], pos_add.inputs[0])
        ng.links.new(half_axis_vecs[axis].outputs["Vector"], pos_add.inputs[1])

        direction = ng.nodes.new("FunctionNodeInputVector")
        direction.location = (-200, -1400 - 150 * i)
        vec = [0.0, 0.0, 0.0]
        vec[i] = 1.0
        direction.vector = vec

        lin = ng.nodes.new("GeometryNodeGizmoLinear")
        lin.name = f"Size {axis} Gizmo"
        lin.label = f"Size {axis} Gizmo"
        lin.location = (100, -900 - 150 * i)
        ng.links.new(sep_size.outputs[axis], lin.inputs["Value"])
        ng.links.new(pos_add.outputs["Vector"], lin.inputs["Position"])
        ng.links.new(direction.outputs["Vector"], lin.inputs["Direction"])

        up = ng.nodes.new("FunctionNodeInputVector")
        up.location = (100, -1900 - 150 * i)
        upvec = [0.0, 0.0, 0.0]
        upvec[(i + 1) % 3] = 1.0
        up.vector = upvec

        dial = ng.nodes.new("GeometryNodeGizmoDial")
        dial.name = f"Division {axis} Gizmo"
        dial.label = f"Division {axis} Gizmo"
        dial.location = (400, -900 - 150 * i)
        dial.inputs["Radius"].default_value = 0.4
        dial.inputs["Screen Space"].default_value = True
        ng.links.new(group_in.outputs[f"Division {axis}"], dial.inputs["Value"])
        ng.links.new(pos_add.outputs["Vector"], dial.inputs["Position"])
        ng.links.new(up.outputs["Vector"], dial.inputs["Up"])

    return ng


def build_cube_gn(name="Cube"):
    """Object with an empty base mesh + the parametric Cube GN modifier."""
    mesh = bpy.data.meshes.new(name)
    obj = bpy.data.objects.new(name, mesh)
    mod = obj.modifiers.new("Modern Cube", "NODES")
    mod.node_group = build_cube_gn_group()

    # The modifier's own stored input value does NOT inherit the interface's
    # default_value automatically for Material sockets — set it explicitly,
    # otherwise it ships as None (invisible/fallback-grey in the viewport).
    mat_item = next(
        it for it in mod.node_group.interface.items_tree
        if it.item_type == "SOCKET" and it.socket_type == "NodeSocketMaterial"
    )
    getattr(mod.properties.inputs, mat_item.identifier).value = clay

    return obj


# ---------------------------------------------------------------------------
# Shading / modifiers / asset metadata helpers
# ---------------------------------------------------------------------------


def add_bevel(obj, width, segments):
    mod = obj.modifiers.new("Bevel", "BEVEL")
    mod.width = width
    mod.segments = segments
    mod.limit_method = "ANGLE"
    mod.angle_limit = math.radians(35)


def apply_shading(obj, mode):
    if mode == "flat":
        for p in obj.data.polygons:
            p.use_smooth = False
        return
    for p in obj.data.polygons:
        p.use_smooth = True
    if mode == "auto":
        with bpy.context.temp_override(active_object=obj, selected_editable_objects=[obj], object=obj):
            bpy.ops.object.shade_auto_smooth(angle=math.radians(30))


def find_gn_material_input(obj):
    """Return the modifier's Material input (properties.inputs.SocketN), if any.

    Geometry Nodes-generated geometry ignores obj.data.materials unless a
    Set Material node inside the tree is wired to an exposed Material input
    — that's the only place swapping the material actually has an effect.
    """
    for mod in obj.modifiers:
        if mod.type != "NODES" or not mod.node_group:
            continue
        for item in mod.node_group.interface.items_tree:
            if (item.item_type == "SOCKET" and item.in_out == "INPUT"
                    and item.socket_type == "NodeSocketMaterial"):
                return getattr(mod.properties.inputs, item.identifier)
    return None


def swap_material(obj, material):
    """Swap obj's material for `material`; returns a callback that restores it."""
    gn_input = find_gn_material_input(obj)
    if gn_input is not None:
        old = gn_input.value
        gn_input.value = material
        return lambda: setattr(gn_input, "value", old)

    shipped_mats = list(obj.data.materials)
    obj.data.materials.clear()
    obj.data.materials.append(material)

    def restore():
        obj.data.materials.clear()
        for m in shipped_mats:
            obj.data.materials.append(m)

    return restore


def make_asset(obj, catalog_uuid, description, tags):
    obj.asset_mark()
    ad = obj.asset_data
    ad.catalog_id = catalog_uuid
    ad.description = description
    for t in tags:
        ad.tags.new(t)


def render_thumbnail(obj, filepath, color):
    hidden = []
    for o in scene.collection.all_objects:
        if o is obj or o.type in ("CAMERA", "LIGHT"):
            continue
        if not o.hide_render:
            o.hide_render = True
            hidden.append(o)

    bbox = [obj.matrix_world @ mathutils.Vector(c) for c in obj.bound_box]
    center = sum(bbox, mathutils.Vector((0, 0, 0))) / 8
    radius = max((v - center).length for v in bbox) or 1.0

    cam_dir = mathutils.Vector((1.6, -1.8, 1.3)).normalized()
    cam.location = center + cam_dir * radius * 3.4
    cam.rotation_euler = (center - cam.location).to_track_quat("-Z", "Y").to_euler()

    key.location = cam.location + mathutils.Vector((-1.0, -1.5, 2.0))
    key.rotation_euler = (center - key.location).to_track_quat("-Z", "Y").to_euler()

    # Swap in the random-hue preview material just for this render — the
    # shipped asset keeps its neutral clay material.
    preview_bsdf.inputs["Base Color"].default_value = color
    restore_material = swap_material(obj, preview_mat)
    obj.update_tag(refresh={"DATA"})

    scene.render.filepath = filepath
    bpy.ops.render.render(write_still=True)

    restore_material()
    obj.update_tag(refresh={"DATA"})

    for o in hidden:
        o.hide_render = False


def set_custom_preview(obj, filepath):
    img = bpy.data.images.load(filepath)
    pixels = img.pixels[:]
    w, h = img.size
    prev = obj.preview_ensure()
    prev.image_size = (w, h)
    prev.image_pixels_float[:] = pixels
    bpy.data.images.remove(img)


# ---------------------------------------------------------------------------
# Asset definitions
# ---------------------------------------------------------------------------

ASSETS = [
    # -- Base primitives ----------------------------------------------------
    dict(
        name="Cube", category="base",
        make=lambda: build_cube_gn(),
        shading=None, bevel=None, gn=True,
        description="Parametric cube — Size/Division/pivot are live modifier "
                    "inputs with viewport drag gizmos, not a fixed mesh.",
        tags=["cube", "box", "primitive", "parametric"],
    ),
    dict(
        name="Sphere", category="base",
        make=lambda: spawn_via_op(lambda: bpy.ops.mesh.primitive_uv_sphere_add(radius=1, segments=32, ring_count=16)),
        shading="auto", bevel=None,
        description="UV sphere, radius 1m.",
        tags=["sphere", "ball", "primitive"],
    ),
    dict(
        name="Ico Sphere", category="base",
        make=lambda: spawn_via_op(lambda: bpy.ops.mesh.primitive_ico_sphere_add(radius=1, subdivisions=3)),
        shading="auto", bevel=None,
        description="Icosphere, radius 1m, 3 subdivisions.",
        tags=["sphere", "ico", "primitive"],
    ),
    dict(
        name="Cylinder", category="base",
        make=lambda: spawn_via_op(lambda: bpy.ops.mesh.primitive_cylinder_add(radius=1, depth=2, vertices=32)),
        shading="auto", bevel=None,
        description="Cylinder, radius 1m, height 2m.",
        tags=["cylinder", "primitive"],
    ),
    dict(
        name="Cone", category="base",
        make=lambda: spawn_via_op(lambda: bpy.ops.mesh.primitive_cone_add(radius1=1, radius2=0, depth=2, vertices=32)),
        shading="auto", bevel=None,
        description="Cone, base radius 1m, height 2m.",
        tags=["cone", "primitive"],
    ),
    dict(
        name="Torus", category="base",
        make=lambda: spawn_via_op(lambda: bpy.ops.mesh.primitive_torus_add(
            major_radius=1, minor_radius=0.35, major_segments=32, minor_segments=16)),
        shading="auto", bevel=None,
        description="Torus, major radius 1m, minor radius 0.35m.",
        tags=["torus", "donut", "primitive"],
    ),
    dict(
        name="Plane", category="base",
        make=lambda: spawn_via_op(lambda: bpy.ops.mesh.primitive_plane_add(size=2)),
        shading="flat", bevel=None,
        description="Flat 2m plane.",
        tags=["plane", "grid", "primitive"],
    ),
    # -- Hard-surface kit -----------------------------------------------------
    dict(
        name="Rounded Cube", category="kit",
        make=lambda: spawn_via_op(lambda: bpy.ops.mesh.primitive_cube_add(size=2)),
        shading="auto", bevel=(0.15, 6),
        description="2m cube with a soft rounded bevel, kitbash-ready.",
        tags=["cube", "rounded", "kit", "hard-surface"],
    ),
    dict(
        name="Tube", category="kit",
        make=lambda: build_tube(),
        shading="auto", bevel=None,
        description="Hollow cylindrical tube, outer radius 1m, wall thickness 0.35m.",
        tags=["tube", "pipe", "hollow", "kit", "hard-surface"],
    ),
    dict(
        name="Dome", category="kit",
        make=lambda: build_dome(),
        shading="auto", bevel=None,
        description="Half-sphere dome, radius 1m, flat base.",
        tags=["dome", "half-sphere", "kit", "hard-surface"],
    ),
    dict(
        name="Wedge", category="kit",
        make=lambda: build_wedge(),
        shading="auto", bevel=(0.03, 2),
        description="Ramp / wedge block, 2x2x2m footprint.",
        tags=["wedge", "ramp", "kit", "hard-surface"],
    ),
    dict(
        name="Stairs", category="kit",
        make=lambda: build_stairs(),
        shading="flat", bevel=(0.02, 2),
        description="5-step staircase block, 2m wide, 2m tall, 2m deep.",
        tags=["stairs", "steps", "kit", "hard-surface"],
    ),
    dict(
        name="Pyramid", category="kit",
        make=lambda: _make_pyramid(),
        shading="auto", bevel=(0.02, 2),
        description="Square-base pyramid, 2x2m base, 2m tall.",
        tags=["pyramid", "kit", "hard-surface"],
    ),
    dict(
        name="Hex Prism", category="kit",
        make=lambda: spawn_via_op(lambda: bpy.ops.mesh.primitive_cylinder_add(radius=1, depth=2, vertices=6)),
        shading="auto", bevel=(0.02, 2),
        description="Hexagonal prism, radius 1m, height 2m.",
        tags=["hexagon", "prism", "kit", "hard-surface"],
    ),
]


def _make_pyramid():
    bpy.ops.mesh.primitive_cone_add(vertices=4, radius1=math.sqrt(2), radius2=0, depth=2)
    obj = bpy.context.active_object
    obj.rotation_euler[2] = math.radians(45)
    obj.select_set(True)
    with bpy.context.temp_override(active_object=obj, selected_editable_objects=[obj], object=obj):
        bpy.ops.object.transform_apply(location=False, rotation=True, scale=False)
    for c in list(obj.users_collection):
        c.objects.unlink(obj)
    return obj


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------

catalog_for = {"base": CATALOG_BASE, "kit": CATALOG_KIT}
collection_for = {"base": base_col, "kit": kit_col}

for i, spec in enumerate(ASSETS):
    obj = spec["make"]()
    obj.name = spec["name"]
    obj.data.name = spec["name"]
    collection_for[spec["category"]].objects.link(obj)
    if not spec.get("gn"):
        obj.data.materials.append(clay)
        if spec["bevel"]:
            add_bevel(obj, *spec["bevel"])
        apply_shading(obj, spec["shading"])

    make_asset(obj, catalog_for[spec["category"]], spec["description"], spec["tags"])

    thumb_path = os.path.join(THUMB_DIR, f"{spec['name'].replace(' ', '_')}.png")
    render_thumbnail(obj, thumb_path, preview_color(i, len(ASSETS)))
    set_custom_preview(obj, thumb_path)

    print(f"Built asset: {spec['name']} ({spec['category']})")

bpy.data.materials.remove(preview_mat)

# ---------------------------------------------------------------------------
# Catalog definition file (lives next to the .blend, read by the Asset Browser)
# ---------------------------------------------------------------------------

CATS_CONTENT = f"""# This is an Asset Catalog Definition file for Blender.
#
# Empty lines and lines starting with `#` will be ignored.
# The first non-ignored line should be the version indicator.
# Other lines are of the format "UUID:catalog/path/for/assets:simple catalog name"

VERSION 1

{CATALOG_BASE}:Base:Base
{CATALOG_KIT}:Hard Surface Kit:Hard-Surface-Kit
"""

with open(CATS_PATH, "w") as f:
    f.write(CATS_CONTENT)

# ---------------------------------------------------------------------------
# Save
# ---------------------------------------------------------------------------

bpy.ops.wm.save_as_mainfile(filepath=BLEND_PATH)
print(f"\nSaved {BLEND_PATH}")
print(f"Wrote {CATS_PATH}")
print(f"Thumbnails rendered to {THUMB_DIR} (not shipped, embedded as custom previews instead)")
