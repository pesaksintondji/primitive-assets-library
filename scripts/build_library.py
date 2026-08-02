"""
Regenerates assets/primitives.blend from scratch.

Run headless with Blender 4.1+ :

    blender --background --python scripts/build_library.py

The script is fully deterministic and idempotent: re-running it always
rebuilds the same assets, re-renders their preview thumbnails and
re-marks them as Blender assets with stable catalog UUIDs (so existing
catalog assignments in blender_assets.cats.txt keep matching).
"""

import bpy
import colorsys
import math
import os
import mathutils
import numpy as np

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

# Thumbnail-only wireframe overlay material (dark, unlit-ish so edges read
# clearly against any hue).
preview_wire_mat = bpy.data.materials.new("Preview Wire")
preview_wire_mat.use_nodes = True
preview_wire_bsdf = preview_wire_mat.node_tree.nodes["Principled BSDF"]
preview_wire_bsdf.inputs["Base Color"].default_value = (0.02, 0.02, 0.02, 1.0)
preview_wire_bsdf.inputs["Roughness"].default_value = 0.8

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
    # NOTE: must index by string "False"/"True" here, not the Python bools --
    # bool is a subclass of int, so switch_node.inputs[False]/[True] silently
    # resolve to positional indices 0/1 (Switch/False) instead of by name,
    # clobbering the Switch link itself.
    ng.links.new(transform_node.outputs["Geometry"], switch_node.inputs["False"])
    ng.links.new(sba_node.outputs[0], switch_node.inputs["True"])

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
        lin.color_id = axis
        ng.links.new(sep_size.outputs[axis], lin.inputs["Value"])
        ng.links.new(pos_add.outputs["Vector"], lin.inputs["Position"])
        ng.links.new(direction.outputs["Vector"], lin.inputs["Direction"])

        # Up = the same axis being controlled, so the ring is drawn
        # perpendicular to (spinning around) that axis — turning it with the
        # right-hand rule around +X/+Y/+Z increases the value.
        up = ng.nodes.new("FunctionNodeInputVector")
        up.location = (100, -1900 - 150 * i)
        up.vector = vec

        dial = ng.nodes.new("GeometryNodeGizmoDial")
        dial.name = f"Division {axis} Gizmo"
        dial.label = f"Division {axis} Gizmo"
        dial.location = (400, -900 - 150 * i)
        dial.color_id = axis
        dial.inputs["Radius"].default_value = 0.4
        dial.inputs["Screen Space"].default_value = True
        ng.links.new(group_in.outputs[f"Division {axis}"], dial.inputs["Value"])
        ng.links.new(pos_add.outputs["Vector"], dial.inputs["Position"])
        ng.links.new(up.outputs["Vector"], dial.inputs["Up"])

    # --- Pivot move gizmo (3-axis translate arrows), driving Corner Ratio
    # through the same offset math used to place the shape/other gizmos.
    combine_tf = ng.nodes.new("FunctionNodeCombineTransform")
    combine_tf.location = (100, -2400)
    ng.links.new(offset_node.outputs["Vector"], combine_tf.inputs["Translation"])

    pivot_gizmo = ng.nodes.new("GeometryNodeGizmoTransform")
    pivot_gizmo.name = "Pivot Gizmo"
    pivot_gizmo.label = "Pivot Gizmo"
    pivot_gizmo.location = (400, -2400)
    pivot_gizmo.use_rotation_x = pivot_gizmo.use_rotation_y = pivot_gizmo.use_rotation_z = False
    pivot_gizmo.use_scale_x = pivot_gizmo.use_scale_y = pivot_gizmo.use_scale_z = False
    ng.links.new(combine_tf.outputs["Transform"], pivot_gizmo.inputs["Value"])
    ng.links.new(offset_node.outputs["Vector"], pivot_gizmo.inputs["Position"])

    return ng


def make_gn_object(name, node_group):
    """Object with an empty base mesh + a NODES modifier running node_group,
    with the Material input initialized (see build_cube_gn's comment above —
    it does not inherit the interface default on its own).
    """
    mesh = bpy.data.meshes.new(name)
    obj = bpy.data.objects.new(name, mesh)
    mod = obj.modifiers.new(f"Modern {name}", "NODES")
    mod.node_group = node_group
    mat_item = next(
        it for it in node_group.interface.items_tree
        if it.item_type == "SOCKET" and it.socket_type == "NodeSocketMaterial"
    )
    getattr(mod.properties.inputs, mat_item.identifier).value = clay
    return obj


# ---------------------------------------------------------------------------
# Shared node-group building blocks for the remaining parametric primitives
# ---------------------------------------------------------------------------


def add_common_interface(iface, smooth_default=False):
    """Smooth / Smooth Angle / Material — the tail every primitive shares."""
    smooth_in = iface.new_socket(name="Smooth", in_out="INPUT", socket_type="NodeSocketBool")
    smooth_in.default_value = smooth_default
    angle_in = iface.new_socket(name="Smooth Angle", in_out="INPUT", socket_type="NodeSocketFloat")
    angle_in.subtype = "ANGLE"
    angle_in.default_value = math.radians(30)
    mat_in = iface.new_socket(name="Material", in_out="INPUT", socket_type="NodeSocketMaterial")
    mat_in.default_value = clay


def add_smooth_material_tail(ng, group_in, group_out, mesh_socket, sba):
    """mesh_socket -> [Smooth by Angle switch] -> Set Material -> Group Output."""
    sba_node = ng.nodes.new("GeometryNodeGroup")
    sba_node.node_tree = sba
    ng.links.new(mesh_socket, sba_node.inputs[0])
    ng.links.new(group_in.outputs["Smooth Angle"], sba_node.inputs["Angle"])

    switch_node = ng.nodes.new("GeometryNodeSwitch")
    switch_node.input_type = "GEOMETRY"
    ng.links.new(group_in.outputs["Smooth"], switch_node.inputs["Switch"])
    # See the identical note in build_cube_gn_group: index by "False"/"True"
    # strings, never the Python bools (they alias to positional 0/1).
    ng.links.new(mesh_socket, switch_node.inputs["False"])
    ng.links.new(sba_node.outputs[0], switch_node.inputs["True"])

    set_mat_node = ng.nodes.new("GeometryNodeSetMaterial")
    ng.links.new(switch_node.outputs[0], set_mat_node.inputs["Geometry"])
    ng.links.new(group_in.outputs["Material"], set_mat_node.inputs["Material"])
    ng.links.new(set_mat_node.outputs["Geometry"], group_out.inputs["Geometry"])


def const_vec(ng, xyz):
    n = ng.nodes.new("FunctionNodeInputVector")
    n.vector = list(xyz)
    return n.outputs["Vector"]


def combine_point(ng, x=None, y=None, z=None):
    """A Vector socket built from up to 3 (optional) float sockets."""
    c = ng.nodes.new("ShaderNodeCombineXYZ")
    if x is not None:
        ng.links.new(x, c.inputs["X"])
    if y is not None:
        ng.links.new(y, c.inputs["Y"])
    if z is not None:
        ng.links.new(z, c.inputs["Z"])
    return c.outputs["Vector"]


def negate(ng, socket):
    m = ng.nodes.new("ShaderNodeMath")
    m.operation = "MULTIPLY"
    m.inputs[1].default_value = -1.0
    ng.links.new(socket, m.inputs[0])
    return m.outputs["Value"]


def half(ng, socket):
    m = ng.nodes.new("ShaderNodeMath")
    m.operation = "MULTIPLY"
    m.inputs[1].default_value = 0.5
    ng.links.new(socket, m.inputs[0])
    return m.outputs["Value"]


def add_scalars(ng, a, b):
    m = ng.nodes.new("ShaderNodeMath")
    m.operation = "ADD"
    ng.links.new(a, m.inputs[0])
    ng.links.new(b, m.inputs[1])
    return m.outputs["Value"]


def divisions_to_vertices(ng, division_socket):
    """Division count (0 = no cuts) -> vertex count (Blender primitive nodes
    want vertex counts, e.g. Vertices X on Mesh Cube/Grid)."""
    m = ng.nodes.new("ShaderNodeMath")
    m.operation = "ADD"
    m.inputs[1].default_value = 2.0
    ng.links.new(division_socket, m.inputs[0])
    return m.outputs["Value"]


def add_linear_gizmo(ng, label, value_socket, position_socket, direction_socket, color_id):
    g = ng.nodes.new("GeometryNodeGizmoLinear")
    g.name = label
    g.label = label
    g.color_id = color_id
    ng.links.new(value_socket, g.inputs["Value"])
    ng.links.new(position_socket, g.inputs["Position"])
    ng.links.new(direction_socket, g.inputs["Direction"])
    return g


def add_dial_gizmo(ng, label, value_socket, position_socket, up_socket, color_id, radius=0.4):
    g = ng.nodes.new("GeometryNodeGizmoDial")
    g.name = label
    g.label = label
    g.color_id = color_id
    g.inputs["Radius"].default_value = radius
    g.inputs["Screen Space"].default_value = True
    ng.links.new(value_socket, g.inputs["Value"])
    ng.links.new(position_socket, g.inputs["Position"])
    ng.links.new(up_socket, g.inputs["Up"])
    return g


def build_sphere_gn_group(name="[PrimLib] Sphere"):
    sba = ensure_smooth_by_angle_group()
    ng = bpy.data.node_groups.new(name, "GeometryNodeTree")
    iface = ng.interface
    iface.new_socket(name="Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    iface.new_socket(name="Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    radius_in = iface.new_socket(name="Radius", in_out="INPUT", socket_type="NodeSocketFloat")
    radius_in.default_value = 1.0
    radius_in.min_value = 0.001
    seg_in = iface.new_socket(name="Segments", in_out="INPUT", socket_type="NodeSocketInt")
    seg_in.default_value = 32
    seg_in.min_value = 3
    ring_in = iface.new_socket(name="Rings", in_out="INPUT", socket_type="NodeSocketInt")
    ring_in.default_value = 16
    ring_in.min_value = 2
    add_common_interface(iface, smooth_default=True)

    group_in = ng.nodes.new("NodeGroupInput")
    group_out = ng.nodes.new("NodeGroupOutput")

    sphere_node = ng.nodes.new("GeometryNodeMeshUVSphere")
    ng.links.new(group_in.outputs["Segments"], sphere_node.inputs["Segments"])
    ng.links.new(group_in.outputs["Rings"], sphere_node.inputs["Rings"])
    ng.links.new(group_in.outputs["Radius"], sphere_node.inputs["Radius"])

    add_smooth_material_tail(ng, group_in, group_out, sphere_node.outputs["Mesh"], sba)

    add_linear_gizmo(ng, "Radius Gizmo", group_in.outputs["Radius"],
                      combine_point(ng, x=group_in.outputs["Radius"]), const_vec(ng, (1, 0, 0)), "X")
    add_dial_gizmo(ng, "Segments Gizmo", group_in.outputs["Segments"],
                    combine_point(ng, y=group_in.outputs["Radius"]), const_vec(ng, (0, 1, 0)), "Y")
    add_dial_gizmo(ng, "Rings Gizmo", group_in.outputs["Rings"],
                    combine_point(ng, z=group_in.outputs["Radius"]), const_vec(ng, (0, 0, 1)), "Z")

    return ng


def build_icosphere_gn_group(name="[PrimLib] Ico Sphere"):
    sba = ensure_smooth_by_angle_group()
    ng = bpy.data.node_groups.new(name, "GeometryNodeTree")
    iface = ng.interface
    iface.new_socket(name="Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    iface.new_socket(name="Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    radius_in = iface.new_socket(name="Radius", in_out="INPUT", socket_type="NodeSocketFloat")
    radius_in.default_value = 1.0
    radius_in.min_value = 0.001
    sub_in = iface.new_socket(name="Subdivisions", in_out="INPUT", socket_type="NodeSocketInt")
    sub_in.default_value = 3
    sub_in.min_value = 1
    sub_in.max_value = 8
    add_common_interface(iface, smooth_default=True)

    group_in = ng.nodes.new("NodeGroupInput")
    group_out = ng.nodes.new("NodeGroupOutput")

    ico_node = ng.nodes.new("GeometryNodeMeshIcoSphere")
    ng.links.new(group_in.outputs["Radius"], ico_node.inputs["Radius"])
    ng.links.new(group_in.outputs["Subdivisions"], ico_node.inputs["Subdivisions"])

    add_smooth_material_tail(ng, group_in, group_out, ico_node.outputs["Mesh"], sba)

    add_linear_gizmo(ng, "Radius Gizmo", group_in.outputs["Radius"],
                      combine_point(ng, x=group_in.outputs["Radius"]), const_vec(ng, (1, 0, 0)), "X")
    add_dial_gizmo(ng, "Subdivisions Gizmo", group_in.outputs["Subdivisions"],
                    combine_point(ng, z=group_in.outputs["Radius"]), const_vec(ng, (0, 0, 1)), "Z")

    return ng


def build_cylinder_gn_group(name="[PrimLib] Cylinder"):
    sba = ensure_smooth_by_angle_group()
    ng = bpy.data.node_groups.new(name, "GeometryNodeTree")
    iface = ng.interface
    iface.new_socket(name="Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    iface.new_socket(name="Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    radius_in = iface.new_socket(name="Radius", in_out="INPUT", socket_type="NodeSocketFloat")
    radius_in.default_value = 1.0
    radius_in.min_value = 0.001
    depth_in = iface.new_socket(name="Depth", in_out="INPUT", socket_type="NodeSocketFloat")
    depth_in.default_value = 2.0
    depth_in.min_value = 0.001
    vert_in = iface.new_socket(name="Vertices", in_out="INPUT", socket_type="NodeSocketInt")
    vert_in.default_value = 32
    vert_in.min_value = 3
    add_common_interface(iface, smooth_default=True)

    group_in = ng.nodes.new("NodeGroupInput")
    group_out = ng.nodes.new("NodeGroupOutput")

    cyl_node = ng.nodes.new("GeometryNodeMeshCylinder")
    ng.links.new(group_in.outputs["Vertices"], cyl_node.inputs["Vertices"])
    ng.links.new(group_in.outputs["Radius"], cyl_node.inputs["Radius"])
    ng.links.new(group_in.outputs["Depth"], cyl_node.inputs["Depth"])

    add_smooth_material_tail(ng, group_in, group_out, cyl_node.outputs["Mesh"], sba)

    half_depth = half(ng, group_in.outputs["Depth"])
    add_linear_gizmo(ng, "Radius Gizmo", group_in.outputs["Radius"],
                      combine_point(ng, x=group_in.outputs["Radius"]), const_vec(ng, (1, 0, 0)), "X")
    add_linear_gizmo(ng, "Depth Gizmo", group_in.outputs["Depth"],
                      combine_point(ng, z=half_depth), const_vec(ng, (0, 0, 1)), "Z")
    add_dial_gizmo(ng, "Vertices Gizmo",
                    group_in.outputs["Vertices"],
                    combine_point(ng, x=group_in.outputs["Radius"], z=half_depth),
                    const_vec(ng, (0, 0, 1)), "Y")

    return ng


def build_cone_gn_group(name="[PrimLib] Cone"):
    sba = ensure_smooth_by_angle_group()
    ng = bpy.data.node_groups.new(name, "GeometryNodeTree")
    iface = ng.interface
    iface.new_socket(name="Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    iface.new_socket(name="Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    rbot_in = iface.new_socket(name="Radius Bottom", in_out="INPUT", socket_type="NodeSocketFloat")
    rbot_in.default_value = 1.0
    rbot_in.min_value = 0.0
    rtop_in = iface.new_socket(name="Radius Top", in_out="INPUT", socket_type="NodeSocketFloat")
    rtop_in.default_value = 0.0
    rtop_in.min_value = 0.0
    depth_in = iface.new_socket(name="Depth", in_out="INPUT", socket_type="NodeSocketFloat")
    depth_in.default_value = 2.0
    depth_in.min_value = 0.001
    vert_in = iface.new_socket(name="Vertices", in_out="INPUT", socket_type="NodeSocketInt")
    vert_in.default_value = 32
    vert_in.min_value = 3
    add_common_interface(iface, smooth_default=True)

    group_in = ng.nodes.new("NodeGroupInput")
    group_out = ng.nodes.new("NodeGroupOutput")

    cone_node = ng.nodes.new("GeometryNodeMeshCone")
    ng.links.new(group_in.outputs["Vertices"], cone_node.inputs["Vertices"])
    ng.links.new(group_in.outputs["Radius Top"], cone_node.inputs["Radius Top"])
    ng.links.new(group_in.outputs["Radius Bottom"], cone_node.inputs["Radius Bottom"])
    ng.links.new(group_in.outputs["Depth"], cone_node.inputs["Depth"])

    add_smooth_material_tail(ng, group_in, group_out, cone_node.outputs["Mesh"], sba)

    half_depth = half(ng, group_in.outputs["Depth"])
    neg_half_depth = negate(ng, half_depth)
    add_linear_gizmo(ng, "Radius Bottom Gizmo", group_in.outputs["Radius Bottom"],
                      combine_point(ng, x=group_in.outputs["Radius Bottom"], z=neg_half_depth),
                      const_vec(ng, (1, 0, 0)), "X")
    add_linear_gizmo(ng, "Depth Gizmo", group_in.outputs["Depth"],
                      combine_point(ng, z=half_depth), const_vec(ng, (0, 0, 1)), "Z")
    add_dial_gizmo(ng, "Vertices Gizmo",
                    group_in.outputs["Vertices"],
                    combine_point(ng, x=group_in.outputs["Radius Bottom"], z=neg_half_depth),
                    const_vec(ng, (0, 0, 1)), "Y")

    return ng


def build_torus_gn_group(name="[PrimLib] Torus"):
    """No native Torus primitive in Geometry Nodes — swept from two circles
    (the classic path-circle + rotated-profile-circle recipe)."""
    sba = ensure_smooth_by_angle_group()
    ng = bpy.data.node_groups.new(name, "GeometryNodeTree")
    iface = ng.interface
    iface.new_socket(name="Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    iface.new_socket(name="Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    major_in = iface.new_socket(name="Major Radius", in_out="INPUT", socket_type="NodeSocketFloat")
    major_in.default_value = 1.0
    major_in.min_value = 0.001
    minor_in = iface.new_socket(name="Minor Radius", in_out="INPUT", socket_type="NodeSocketFloat")
    minor_in.default_value = 0.35
    minor_in.min_value = 0.001
    majseg_in = iface.new_socket(name="Major Segments", in_out="INPUT", socket_type="NodeSocketInt")
    majseg_in.default_value = 32
    majseg_in.min_value = 3
    minseg_in = iface.new_socket(name="Minor Segments", in_out="INPUT", socket_type="NodeSocketInt")
    minseg_in.default_value = 16
    minseg_in.min_value = 3
    add_common_interface(iface, smooth_default=True)

    group_in = ng.nodes.new("NodeGroupInput")
    group_out = ng.nodes.new("NodeGroupOutput")

    path_circle = ng.nodes.new("GeometryNodeCurvePrimitiveCircle")
    path_circle.mode = "RADIUS"
    ng.links.new(group_in.outputs["Major Radius"], path_circle.inputs["Radius"])
    ng.links.new(group_in.outputs["Major Segments"], path_circle.inputs["Resolution"])

    profile_circle = ng.nodes.new("GeometryNodeCurvePrimitiveCircle")
    profile_circle.mode = "RADIUS"
    ng.links.new(group_in.outputs["Minor Radius"], profile_circle.inputs["Radius"])
    ng.links.new(group_in.outputs["Minor Segments"], profile_circle.inputs["Resolution"])

    curve_to_mesh = ng.nodes.new("GeometryNodeCurveToMesh")
    curve_to_mesh.inputs["Fill Caps"].default_value = False
    ng.links.new(path_circle.outputs["Curve"], curve_to_mesh.inputs["Curve"])
    ng.links.new(profile_circle.outputs["Curve"], curve_to_mesh.inputs["Profile Curve"])

    add_smooth_material_tail(ng, group_in, group_out, curve_to_mesh.outputs["Mesh"], sba)

    outer_radius = add_scalars(ng, group_in.outputs["Major Radius"], group_in.outputs["Minor Radius"])
    add_linear_gizmo(ng, "Major Radius Gizmo", group_in.outputs["Major Radius"],
                      combine_point(ng, x=outer_radius), const_vec(ng, (1, 0, 0)), "X")
    add_linear_gizmo(ng, "Minor Radius Gizmo", group_in.outputs["Minor Radius"],
                      combine_point(ng, x=group_in.outputs["Major Radius"], z=group_in.outputs["Minor Radius"]),
                      const_vec(ng, (0, 0, 1)), "Z")
    add_dial_gizmo(ng, "Major Segments Gizmo", group_in.outputs["Major Segments"],
                    combine_point(ng, y=group_in.outputs["Major Radius"]), const_vec(ng, (0, 1, 0)), "Y")
    add_dial_gizmo(ng, "Minor Segments Gizmo", group_in.outputs["Minor Segments"],
                    combine_point(ng, x=group_in.outputs["Major Radius"], z=group_in.outputs["Minor Radius"]),
                    const_vec(ng, (0, 1, 0)), "Y", radius=0.25)

    return ng


def build_plane_gn_group(name="[PrimLib] Plane"):
    sba = ensure_smooth_by_angle_group()
    ng = bpy.data.node_groups.new(name, "GeometryNodeTree")
    iface = ng.interface
    iface.new_socket(name="Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    iface.new_socket(name="Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    sx_in = iface.new_socket(name="Size X", in_out="INPUT", socket_type="NodeSocketFloat")
    sx_in.default_value = 2.0
    sx_in.min_value = 0.001
    sy_in = iface.new_socket(name="Size Y", in_out="INPUT", socket_type="NodeSocketFloat")
    sy_in.default_value = 2.0
    sy_in.min_value = 0.001
    dx_in = iface.new_socket(name="Division X", in_out="INPUT", socket_type="NodeSocketInt")
    dx_in.default_value = 0
    dx_in.min_value = 0
    dy_in = iface.new_socket(name="Division Y", in_out="INPUT", socket_type="NodeSocketInt")
    dy_in.default_value = 0
    dy_in.min_value = 0
    add_common_interface(iface, smooth_default=False)

    group_in = ng.nodes.new("NodeGroupInput")
    group_out = ng.nodes.new("NodeGroupOutput")

    grid_node = ng.nodes.new("GeometryNodeMeshGrid")
    ng.links.new(group_in.outputs["Size X"], grid_node.inputs["Size X"])
    ng.links.new(group_in.outputs["Size Y"], grid_node.inputs["Size Y"])
    ng.links.new(divisions_to_vertices(ng, group_in.outputs["Division X"]), grid_node.inputs["Vertices X"])
    ng.links.new(divisions_to_vertices(ng, group_in.outputs["Division Y"]), grid_node.inputs["Vertices Y"])

    add_smooth_material_tail(ng, group_in, group_out, grid_node.outputs["Mesh"], sba)

    half_x = half(ng, group_in.outputs["Size X"])
    half_y = half(ng, group_in.outputs["Size Y"])
    add_linear_gizmo(ng, "Size X Gizmo", group_in.outputs["Size X"],
                      combine_point(ng, x=half_x), const_vec(ng, (1, 0, 0)), "X")
    add_linear_gizmo(ng, "Size Y Gizmo", group_in.outputs["Size Y"],
                      combine_point(ng, y=half_y), const_vec(ng, (0, 1, 0)), "Y")
    add_dial_gizmo(ng, "Division X Gizmo", group_in.outputs["Division X"],
                    combine_point(ng, x=half_x), const_vec(ng, (0, 0, 1)), "X")
    add_dial_gizmo(ng, "Division Y Gizmo", group_in.outputs["Division Y"],
                    combine_point(ng, y=half_y), const_vec(ng, (0, 0, 1)), "Y")

    return ng


def add_bevel_tail(ng, group_in, mesh_socket, bevel_width_name="Bevel Width", bevel_segments_name="Bevel Segments"):
    """mesh_socket -> MeshBevel(all edges, Offset=Bevel Width, Segments=Bevel Segments) -> output socket."""
    bevel_node = ng.nodes.new("GeometryNodeMeshBevel")
    bevel_node.inputs["Selection"].default_value = True
    ng.links.new(mesh_socket, bevel_node.inputs["Mesh"])
    ng.links.new(group_in.outputs[bevel_width_name], bevel_node.inputs["Offset"])
    ng.links.new(group_in.outputs[bevel_segments_name], bevel_node.inputs["Segments"])
    return bevel_node.outputs["Mesh"]


def build_rounded_cube_gn_group(name="[PrimLib] Rounded Cube"):
    """Parametric hard-surface cube: Size (X/Y/Z) + a rounded Bevel Width/Segments."""
    sba = ensure_smooth_by_angle_group()
    ng = bpy.data.node_groups.new(name, "GeometryNodeTree")
    iface = ng.interface
    iface.new_socket(name="Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    iface.new_socket(name="Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")

    size_in = iface.new_socket(name="Size", in_out="INPUT", socket_type="NodeSocketVector")
    size_in.default_value = (2.0, 2.0, 2.0)
    size_in.min_value = 0.001

    bw_in = iface.new_socket(name="Bevel Width", in_out="INPUT", socket_type="NodeSocketFloat")
    bw_in.subtype = "DISTANCE"
    bw_in.default_value = 0.15
    bw_in.min_value = 0.0

    bs_in = iface.new_socket(name="Bevel Segments", in_out="INPUT", socket_type="NodeSocketInt")
    bs_in.default_value = 6
    bs_in.min_value = 1
    add_common_interface(iface, smooth_default=True)

    group_in = ng.nodes.new("NodeGroupInput")
    group_out = ng.nodes.new("NodeGroupOutput")

    cube_node = ng.nodes.new("GeometryNodeMeshCube")
    ng.links.new(group_in.outputs["Size"], cube_node.inputs["Size"])

    beveled = add_bevel_tail(ng, group_in, cube_node.outputs["Mesh"])
    add_smooth_material_tail(ng, group_in, group_out, beveled, sba)

    sep_size = ng.nodes.new("ShaderNodeSeparateXYZ")
    ng.links.new(group_in.outputs["Size"], sep_size.inputs["Vector"])
    for axis in ("X", "Y", "Z"):
        h = half(ng, sep_size.outputs[axis])
        direction = const_vec(ng, tuple(1.0 if a == axis else 0.0 for a in ("X", "Y", "Z")))
        add_linear_gizmo(ng, f"Size {axis} Gizmo", sep_size.outputs[axis],
                          combine_point(ng, **{axis.lower(): h}), direction, axis)

    half_x = half(ng, sep_size.outputs["X"])
    add_linear_gizmo(ng, "Bevel Width Gizmo", group_in.outputs["Bevel Width"],
                      combine_point(ng, x=half_x, z=half(ng, sep_size.outputs["Z"])),
                      const_vec(ng, (0, 0, 1)), "PRIMARY")
    add_dial_gizmo(ng, "Bevel Segments Gizmo", group_in.outputs["Bevel Segments"],
                    combine_point(ng, x=negate(ng, half_x), z=half(ng, sep_size.outputs["Z"])),
                    const_vec(ng, (1, 0, 0)), "PRIMARY", radius=0.25)

    return ng


def build_hex_prism_gn_group(name="[PrimLib] Hex Prism"):
    """Parametric N-gon prism (defaults to a hexagon) with a rounded edge bevel."""
    sba = ensure_smooth_by_angle_group()
    ng = bpy.data.node_groups.new(name, "GeometryNodeTree")
    iface = ng.interface
    iface.new_socket(name="Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    iface.new_socket(name="Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")

    radius_in = iface.new_socket(name="Radius", in_out="INPUT", socket_type="NodeSocketFloat")
    radius_in.default_value = 1.0
    radius_in.min_value = 0.001
    depth_in = iface.new_socket(name="Depth", in_out="INPUT", socket_type="NodeSocketFloat")
    depth_in.default_value = 2.0
    depth_in.min_value = 0.001
    vert_in = iface.new_socket(name="Vertices", in_out="INPUT", socket_type="NodeSocketInt")
    vert_in.default_value = 6
    vert_in.min_value = 3

    bw_in = iface.new_socket(name="Bevel Width", in_out="INPUT", socket_type="NodeSocketFloat")
    bw_in.subtype = "DISTANCE"
    bw_in.default_value = 0.02
    bw_in.min_value = 0.0
    bs_in = iface.new_socket(name="Bevel Segments", in_out="INPUT", socket_type="NodeSocketInt")
    bs_in.default_value = 2
    bs_in.min_value = 1
    add_common_interface(iface, smooth_default=False)

    group_in = ng.nodes.new("NodeGroupInput")
    group_out = ng.nodes.new("NodeGroupOutput")

    cyl_node = ng.nodes.new("GeometryNodeMeshCylinder")
    ng.links.new(group_in.outputs["Vertices"], cyl_node.inputs["Vertices"])
    ng.links.new(group_in.outputs["Radius"], cyl_node.inputs["Radius"])
    ng.links.new(group_in.outputs["Depth"], cyl_node.inputs["Depth"])

    beveled = add_bevel_tail(ng, group_in, cyl_node.outputs["Mesh"])
    add_smooth_material_tail(ng, group_in, group_out, beveled, sba)

    add_linear_gizmo(ng, "Radius Gizmo", group_in.outputs["Radius"],
                      combine_point(ng, x=group_in.outputs["Radius"]), const_vec(ng, (1, 0, 0)), "X")
    add_linear_gizmo(ng, "Depth Gizmo", half(ng, group_in.outputs["Depth"]),
                      combine_point(ng, z=half(ng, group_in.outputs["Depth"])), const_vec(ng, (0, 0, 1)), "Z")
    add_dial_gizmo(ng, "Vertices Gizmo", group_in.outputs["Vertices"],
                    combine_point(ng, y=group_in.outputs["Radius"]), const_vec(ng, (0, 1, 0)), "Y")
    add_linear_gizmo(ng, "Bevel Width Gizmo", group_in.outputs["Bevel Width"],
                      combine_point(ng, x=negate(ng, group_in.outputs["Radius"]),
                                    z=half(ng, group_in.outputs["Depth"])),
                      const_vec(ng, (0, 0, 1)), "PRIMARY")

    return ng


def build_dome_gn_group(name="[PrimLib] Dome"):
    """Half-sphere with a flat base: a UV Sphere intersected with a large cube
    cutter whose top face sits exactly at Z=0 (no native hemisphere primitive)."""
    sba = ensure_smooth_by_angle_group()
    ng = bpy.data.node_groups.new(name, "GeometryNodeTree")
    iface = ng.interface
    iface.new_socket(name="Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    iface.new_socket(name="Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")

    radius_in = iface.new_socket(name="Radius", in_out="INPUT", socket_type="NodeSocketFloat")
    radius_in.default_value = 1.0
    radius_in.min_value = 0.001
    seg_in = iface.new_socket(name="Segments", in_out="INPUT", socket_type="NodeSocketInt")
    seg_in.default_value = 32
    seg_in.min_value = 3
    ring_in = iface.new_socket(name="Rings", in_out="INPUT", socket_type="NodeSocketInt")
    ring_in.default_value = 16
    ring_in.min_value = 2
    add_common_interface(iface, smooth_default=True)

    group_in = ng.nodes.new("NodeGroupInput")
    group_out = ng.nodes.new("NodeGroupOutput")

    sphere_node = ng.nodes.new("GeometryNodeMeshUVSphere")
    ng.links.new(group_in.outputs["Segments"], sphere_node.inputs["Segments"])
    ng.links.new(group_in.outputs["Rings"], sphere_node.inputs["Rings"])
    ng.links.new(group_in.outputs["Radius"], sphere_node.inputs["Radius"])

    # Cutter cube: comfortably larger than the sphere in every direction,
    # translated down so its top face sits exactly at Z=0.
    cutter_size = ng.nodes.new("ShaderNodeMath")
    cutter_size.operation = "MULTIPLY"
    cutter_size.inputs[1].default_value = 4.0
    ng.links.new(group_in.outputs["Radius"], cutter_size.inputs[0])

    cutter_node = ng.nodes.new("GeometryNodeMeshCube")
    ng.links.new(combine_point(ng, x=cutter_size.outputs["Value"], y=cutter_size.outputs["Value"],
                                z=cutter_size.outputs["Value"]), cutter_node.inputs["Size"])

    cutter_transform = ng.nodes.new("GeometryNodeTransform")
    ng.links.new(cutter_node.outputs["Mesh"], cutter_transform.inputs["Geometry"])
    ng.links.new(combine_point(ng, z=negate(ng, half(ng, cutter_size.outputs["Value"]))),
                  cutter_transform.inputs["Translation"])

    # DIFFERENCE, not INTERSECT: this Blender build's Mesh Boolean node
    # returns Mesh 2 untouched for INTERSECT/UNION (verified empirically —
    # a real solver bug/limitation), while DIFFERENCE (Mesh 1 - Mesh 2)
    # works correctly. Sphere minus the lower-half cutter = upper hemisphere
    # with a clean flat cap, which is exactly the dome shape we want.
    boolean_node = ng.nodes.new("GeometryNodeMeshBoolean")
    boolean_node.operation = "DIFFERENCE"
    # "Mesh 1"/"Mesh 2" can't be looked up by name here (Blender quirk with
    # this node's multi-input socket naming) — index positionally instead.
    ng.links.new(sphere_node.outputs["Mesh"], boolean_node.inputs[0])
    ng.links.new(cutter_transform.outputs["Geometry"], boolean_node.inputs[1])

    add_smooth_material_tail(ng, group_in, group_out, boolean_node.outputs["Mesh"], sba)

    add_linear_gizmo(ng, "Radius Gizmo", group_in.outputs["Radius"],
                      combine_point(ng, x=group_in.outputs["Radius"]), const_vec(ng, (1, 0, 0)), "X")
    add_dial_gizmo(ng, "Segments Gizmo", group_in.outputs["Segments"],
                    combine_point(ng, y=group_in.outputs["Radius"]), const_vec(ng, (0, 0, 1)), "Y")
    add_dial_gizmo(ng, "Rings Gizmo", group_in.outputs["Rings"],
                    combine_point(ng, x=negate(ng, group_in.outputs["Radius"])), const_vec(ng, (0, 0, 1)), "X",
                    radius=0.25)

    return ng


def build_wedge_gn_group(name="[PrimLib] Wedge"):
    """Ramp / wedge block, built by sweeping a right-triangle profile curve
    along a straight path (no native wedge primitive). Verified empirically:
    with the path running along X, a profile point (x, y, 0) lands at world
    (Y=-x, Z=-y) -- so the profile points below are pre-flipped to land the
    triangle where we want it (front face at -Depth/2 rising to +Height)."""
    sba = ensure_smooth_by_angle_group()
    ng = bpy.data.node_groups.new(name, "GeometryNodeTree")
    iface = ng.interface
    iface.new_socket(name="Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    iface.new_socket(name="Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")

    width_in = iface.new_socket(name="Width", in_out="INPUT", socket_type="NodeSocketFloat")
    width_in.default_value = 2.0
    width_in.min_value = 0.001
    depth_in = iface.new_socket(name="Depth", in_out="INPUT", socket_type="NodeSocketFloat")
    depth_in.default_value = 2.0
    depth_in.min_value = 0.001
    height_in = iface.new_socket(name="Height", in_out="INPUT", socket_type="NodeSocketFloat")
    height_in.default_value = 2.0
    height_in.min_value = 0.001

    bw_in = iface.new_socket(name="Bevel Width", in_out="INPUT", socket_type="NodeSocketFloat")
    bw_in.subtype = "DISTANCE"
    bw_in.default_value = 0.03
    bw_in.min_value = 0.0
    bs_in = iface.new_socket(name="Bevel Segments", in_out="INPUT", socket_type="NodeSocketInt")
    bs_in.default_value = 2
    bs_in.min_value = 1
    add_common_interface(iface, smooth_default=False)

    group_in = ng.nodes.new("NodeGroupInput")
    group_out = ng.nodes.new("NodeGroupOutput")

    half_w = half(ng, group_in.outputs["Width"])
    half_d = half(ng, group_in.outputs["Depth"])
    neg_half_w = negate(ng, half_w)

    path = ng.nodes.new("GeometryNodeCurvePrimitiveLine")
    path.mode = "POINTS"
    ng.links.new(combine_point(ng, x=neg_half_w), path.inputs["Start"])
    ng.links.new(combine_point(ng, x=half_w), path.inputs["End"])

    neg_height = negate(ng, group_in.outputs["Height"])
    profile = ng.nodes.new("GeometryNodeCurvePrimitiveQuadrilateral")
    profile.mode = "POINTS"
    ng.links.new(combine_point(ng, x=half_d), profile.inputs["Point 1"])
    ng.links.new(combine_point(ng, x=half_d, y=neg_height), profile.inputs["Point 2"])
    neg_half_d = negate(ng, half_d)
    ng.links.new(combine_point(ng, x=neg_half_d), profile.inputs["Point 3"])
    ng.links.new(combine_point(ng, x=neg_half_d), profile.inputs["Point 4"])

    c2m = ng.nodes.new("GeometryNodeCurveToMesh")
    c2m.inputs["Fill Caps"].default_value = True
    ng.links.new(path.outputs["Curve"], c2m.inputs["Curve"])
    ng.links.new(profile.outputs["Curve"], c2m.inputs["Profile Curve"])

    beveled = add_bevel_tail(ng, group_in, c2m.outputs["Mesh"])
    add_smooth_material_tail(ng, group_in, group_out, beveled, sba)

    add_linear_gizmo(ng, "Width Gizmo", half_w,
                      combine_point(ng, x=half_w), const_vec(ng, (1, 0, 0)), "X")
    add_linear_gizmo(ng, "Depth Gizmo", half_d,
                      combine_point(ng, y=negate(ng, half_d)), const_vec(ng, (0, 1, 0)), "Y")
    add_linear_gizmo(ng, "Height Gizmo", group_in.outputs["Height"],
                      combine_point(ng, y=negate(ng, half_d), z=group_in.outputs["Height"]),
                      const_vec(ng, (0, 0, 1)), "Z")
    add_linear_gizmo(ng, "Bevel Width Gizmo", group_in.outputs["Bevel Width"],
                      combine_point(ng, x=negate(ng, half_w)), const_vec(ng, (0, 0, 1)), "PRIMARY")

    return ng


def build_tube_gn_group(name="[PrimLib] Tube"):
    """Hollow cylindrical tube: outer cylinder minus a taller inner cylinder
    (poking through both caps so the hole comes out clean)."""
    sba = ensure_smooth_by_angle_group()
    ng = bpy.data.node_groups.new(name, "GeometryNodeTree")
    iface = ng.interface
    iface.new_socket(name="Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    iface.new_socket(name="Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")

    outer_in = iface.new_socket(name="Outer Radius", in_out="INPUT", socket_type="NodeSocketFloat")
    outer_in.default_value = 1.0
    outer_in.min_value = 0.001
    inner_in = iface.new_socket(name="Inner Radius", in_out="INPUT", socket_type="NodeSocketFloat")
    inner_in.default_value = 0.65
    inner_in.min_value = 0.001
    height_in = iface.new_socket(name="Height", in_out="INPUT", socket_type="NodeSocketFloat")
    height_in.default_value = 2.0
    height_in.min_value = 0.001
    div_in = iface.new_socket(name="Div Circle", in_out="INPUT", socket_type="NodeSocketInt")
    div_in.default_value = 32
    div_in.min_value = 3
    add_common_interface(iface, smooth_default=True)

    group_in = ng.nodes.new("NodeGroupInput")
    group_out = ng.nodes.new("NodeGroupOutput")

    outer_cyl = ng.nodes.new("GeometryNodeMeshCylinder")
    ng.links.new(group_in.outputs["Div Circle"], outer_cyl.inputs["Vertices"])
    ng.links.new(group_in.outputs["Outer Radius"], outer_cyl.inputs["Radius"])
    ng.links.new(group_in.outputs["Height"], outer_cyl.inputs["Depth"])

    inner_height = ng.nodes.new("ShaderNodeMath")
    inner_height.operation = "MULTIPLY"
    inner_height.inputs[1].default_value = 1.1
    ng.links.new(group_in.outputs["Height"], inner_height.inputs[0])

    inner_cyl = ng.nodes.new("GeometryNodeMeshCylinder")
    ng.links.new(group_in.outputs["Div Circle"], inner_cyl.inputs["Vertices"])
    ng.links.new(group_in.outputs["Inner Radius"], inner_cyl.inputs["Radius"])
    ng.links.new(inner_height.outputs["Value"], inner_cyl.inputs["Depth"])

    boolean_node = ng.nodes.new("GeometryNodeMeshBoolean")
    boolean_node.operation = "DIFFERENCE"
    ng.links.new(outer_cyl.outputs["Mesh"], boolean_node.inputs[0])
    ng.links.new(inner_cyl.outputs["Mesh"], boolean_node.inputs[1])

    add_smooth_material_tail(ng, group_in, group_out, boolean_node.outputs["Mesh"], sba)

    add_linear_gizmo(ng, "Outer Radius Gizmo", group_in.outputs["Outer Radius"],
                      combine_point(ng, x=group_in.outputs["Outer Radius"]), const_vec(ng, (1, 0, 0)), "X")
    add_linear_gizmo(ng, "Inner Radius Gizmo", group_in.outputs["Inner Radius"],
                      combine_point(ng, x=negate(ng, group_in.outputs["Inner Radius"])),
                      const_vec(ng, (-1, 0, 0)), "X")
    add_linear_gizmo(ng, "Height Gizmo", half(ng, group_in.outputs["Height"]),
                      combine_point(ng, z=half(ng, group_in.outputs["Height"])), const_vec(ng, (0, 0, 1)), "Z")
    add_dial_gizmo(ng, "Div Circle Gizmo", group_in.outputs["Div Circle"],
                    combine_point(ng, y=group_in.outputs["Outer Radius"]), const_vec(ng, (0, 0, 1)), "Y")

    return ng


def build_pyramid_gn_group(name="[PrimLib] Pyramid"):
    """Square pyramid: a 4-vertex Mesh Cone, radius derived from Base Size so
    the exposed parameter is an edge length, then rotated 45 degrees so the
    base sits square to the X/Y axes instead of diamond-oriented."""
    sba = ensure_smooth_by_angle_group()
    ng = bpy.data.node_groups.new(name, "GeometryNodeTree")
    iface = ng.interface
    iface.new_socket(name="Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    iface.new_socket(name="Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")

    base_in = iface.new_socket(name="Base Size", in_out="INPUT", socket_type="NodeSocketFloat")
    base_in.default_value = 2.0
    base_in.min_value = 0.001
    height_in = iface.new_socket(name="Height", in_out="INPUT", socket_type="NodeSocketFloat")
    height_in.default_value = 2.0
    height_in.min_value = 0.001
    add_common_interface(iface, smooth_default=False)

    group_in = ng.nodes.new("NodeGroupInput")
    group_out = ng.nodes.new("NodeGroupOutput")

    base_radius = ng.nodes.new("ShaderNodeMath")
    base_radius.operation = "MULTIPLY"
    base_radius.inputs[1].default_value = math.sqrt(2) / 2
    ng.links.new(group_in.outputs["Base Size"], base_radius.inputs[0])

    cone_node = ng.nodes.new("GeometryNodeMeshCone")
    cone_node.inputs["Vertices"].default_value = 4
    cone_node.inputs["Radius Top"].default_value = 0.0
    ng.links.new(base_radius.outputs["Value"], cone_node.inputs["Radius Bottom"])
    ng.links.new(group_in.outputs["Height"], cone_node.inputs["Depth"])

    tf = ng.nodes.new("GeometryNodeTransform")
    tf.inputs["Rotation"].default_value = (0.0, 0.0, math.radians(45.0))
    ng.links.new(cone_node.outputs["Mesh"], tf.inputs["Geometry"])

    add_smooth_material_tail(ng, group_in, group_out, tf.outputs["Geometry"], sba)

    add_linear_gizmo(ng, "Base Size Gizmo", half(ng, group_in.outputs["Base Size"]),
                      combine_point(ng, x=half(ng, group_in.outputs["Base Size"])), const_vec(ng, (1, 0, 0)), "X")
    add_linear_gizmo(ng, "Height Gizmo", half(ng, group_in.outputs["Height"]),
                      combine_point(ng, z=half(ng, group_in.outputs["Height"])), const_vec(ng, (0, 0, 1)), "Z")

    return ng


def build_stairs_gn_group(name="[PrimLib] Stairs"):
    """Staircase block built with a Repeat Zone: each iteration adds one
    step (a box spanning that step's depth slice, tall enough to reach that
    step's height) into an accumulating Join Geometry."""
    sba = ensure_smooth_by_angle_group()
    ng = bpy.data.node_groups.new(name, "GeometryNodeTree")
    iface = ng.interface
    iface.new_socket(name="Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    iface.new_socket(name="Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")

    width_in = iface.new_socket(name="Width", in_out="INPUT", socket_type="NodeSocketFloat")
    width_in.default_value = 2.0
    width_in.min_value = 0.001
    depth_in = iface.new_socket(name="Depth", in_out="INPUT", socket_type="NodeSocketFloat")
    depth_in.default_value = 2.0
    depth_in.min_value = 0.001
    height_in = iface.new_socket(name="Height", in_out="INPUT", socket_type="NodeSocketFloat")
    height_in.default_value = 2.0
    height_in.min_value = 0.001
    steps_in = iface.new_socket(name="Steps", in_out="INPUT", socket_type="NodeSocketInt")
    steps_in.default_value = 5
    steps_in.min_value = 1
    add_common_interface(iface, smooth_default=False)

    group_in = ng.nodes.new("NodeGroupInput")
    group_out = ng.nodes.new("NodeGroupOutput")

    steps_f = ng.nodes.new("ShaderNodeMath")
    steps_f.operation = "MULTIPLY"
    steps_f.inputs[1].default_value = 1.0
    ng.links.new(group_in.outputs["Steps"], steps_f.inputs[0])

    step_depth = ng.nodes.new("ShaderNodeMath")
    step_depth.operation = "DIVIDE"
    ng.links.new(group_in.outputs["Depth"], step_depth.inputs[0])
    ng.links.new(steps_f.outputs["Value"], step_depth.inputs[1])

    step_height = ng.nodes.new("ShaderNodeMath")
    step_height.operation = "DIVIDE"
    ng.links.new(group_in.outputs["Height"], step_height.inputs[0])
    ng.links.new(steps_f.outputs["Value"], step_height.inputs[1])

    half_depth = half(ng, group_in.outputs["Depth"])

    rep_out = ng.nodes.new("GeometryNodeRepeatOutput")
    rep_in = ng.nodes.new("GeometryNodeRepeatInput")
    rep_in.pair_with_output(rep_out)
    ng.links.new(group_in.outputs["Steps"], rep_in.inputs["Iterations"])

    iter_plus1 = ng.nodes.new("ShaderNodeMath")
    iter_plus1.operation = "ADD"
    iter_plus1.inputs[1].default_value = 1.0
    ng.links.new(rep_in.outputs["Iteration"], iter_plus1.inputs[0])

    box_h = ng.nodes.new("ShaderNodeMath")
    box_h.operation = "MULTIPLY"
    ng.links.new(iter_plus1.outputs["Value"], box_h.inputs[0])
    ng.links.new(step_height.outputs["Value"], box_h.inputs[1])

    size_combine = ng.nodes.new("ShaderNodeCombineXYZ")
    ng.links.new(group_in.outputs["Width"], size_combine.inputs["X"])
    ng.links.new(step_depth.outputs["Value"], size_combine.inputs["Y"])
    ng.links.new(box_h.outputs["Value"], size_combine.inputs["Z"])

    step_cube = ng.nodes.new("GeometryNodeMeshCube")
    ng.links.new(size_combine.outputs["Vector"], step_cube.inputs["Size"])

    y0 = ng.nodes.new("ShaderNodeMath")
    y0.operation = "MULTIPLY"
    ng.links.new(rep_in.outputs["Iteration"], y0.inputs[0])
    ng.links.new(step_depth.outputs["Value"], y0.inputs[1])

    y1 = ng.nodes.new("ShaderNodeMath")
    y1.operation = "SUBTRACT"
    ng.links.new(y0.outputs["Value"], y1.inputs[0])
    ng.links.new(half_depth, y1.inputs[1])

    y_center = ng.nodes.new("ShaderNodeMath")
    y_center.operation = "ADD"
    ng.links.new(y1.outputs["Value"], y_center.inputs[0])
    ng.links.new(half(ng, step_depth.outputs["Value"]), y_center.inputs[1])

    z_center = half(ng, box_h.outputs["Value"])

    trans_combine = ng.nodes.new("ShaderNodeCombineXYZ")
    ng.links.new(y_center.outputs["Value"], trans_combine.inputs["Y"])
    ng.links.new(z_center, trans_combine.inputs["Z"])

    step_tf = ng.nodes.new("GeometryNodeTransform")
    ng.links.new(step_cube.outputs["Mesh"], step_tf.inputs["Geometry"])
    ng.links.new(trans_combine.outputs["Vector"], step_tf.inputs["Translation"])

    join = ng.nodes.new("GeometryNodeJoinGeometry")
    ng.links.new(rep_in.outputs["Geometry"], join.inputs["Geometry"])
    ng.links.new(step_tf.outputs["Geometry"], join.inputs["Geometry"])
    ng.links.new(join.outputs["Geometry"], rep_out.inputs["Geometry"])

    add_smooth_material_tail(ng, group_in, group_out, rep_out.outputs["Geometry"], sba)

    add_linear_gizmo(ng, "Width Gizmo", half(ng, group_in.outputs["Width"]),
                      combine_point(ng, x=half(ng, group_in.outputs["Width"])), const_vec(ng, (1, 0, 0)), "X")
    add_linear_gizmo(ng, "Depth Gizmo", half_depth,
                      combine_point(ng, y=half_depth), const_vec(ng, (0, 1, 0)), "Y")
    add_linear_gizmo(ng, "Height Gizmo", group_in.outputs["Height"],
                      combine_point(ng, y=half_depth, z=group_in.outputs["Height"]),
                      const_vec(ng, (0, 0, 1)), "Z")
    add_dial_gizmo(ng, "Steps Gizmo", group_in.outputs["Steps"],
                    combine_point(ng, x=negate(ng, half(ng, group_in.outputs["Width"]))),
                    const_vec(ng, (0, 0, 1)), "PRIMARY")

    return ng


def build_quad_sphere_gn_group(name="[PrimLib] Quad Sphere"):
    """Cube-sphere: a subdivided cube with every vertex pushed out to Radius
    (no native quad-sphere primitive node)."""
    sba = ensure_smooth_by_angle_group()
    ng = bpy.data.node_groups.new(name, "GeometryNodeTree")
    iface = ng.interface
    iface.new_socket(name="Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    iface.new_socket(name="Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")

    radius_in = iface.new_socket(name="Radius", in_out="INPUT", socket_type="NodeSocketFloat")
    radius_in.default_value = 1.0
    radius_in.min_value = 0.001
    sub_in = iface.new_socket(name="Subdivisions", in_out="INPUT", socket_type="NodeSocketInt")
    sub_in.default_value = 3
    sub_in.min_value = 1
    sub_in.max_value = 7
    add_common_interface(iface, smooth_default=True)

    group_in = ng.nodes.new("NodeGroupInput")
    group_out = ng.nodes.new("NodeGroupOutput")

    cube_node = ng.nodes.new("GeometryNodeMeshCube")
    cube_node.inputs["Size"].default_value = (2.0, 2.0, 2.0)

    subdiv_node = ng.nodes.new("GeometryNodeSubdivideMesh")
    ng.links.new(cube_node.outputs["Mesh"], subdiv_node.inputs["Mesh"])
    ng.links.new(group_in.outputs["Subdivisions"], subdiv_node.inputs["Level"])

    position_node = ng.nodes.new("GeometryNodeInputPosition")
    normalize_node = ng.nodes.new("ShaderNodeVectorMath")
    normalize_node.operation = "NORMALIZE"
    ng.links.new(position_node.outputs["Position"], normalize_node.inputs[0])

    scale_node = ng.nodes.new("ShaderNodeVectorMath")
    scale_node.operation = "SCALE"
    ng.links.new(normalize_node.outputs["Vector"], scale_node.inputs["Vector"])
    ng.links.new(group_in.outputs["Radius"], scale_node.inputs["Scale"])

    set_pos_node = ng.nodes.new("GeometryNodeSetPosition")
    ng.links.new(subdiv_node.outputs["Mesh"], set_pos_node.inputs["Geometry"])
    ng.links.new(scale_node.outputs["Vector"], set_pos_node.inputs["Position"])

    add_smooth_material_tail(ng, group_in, group_out, set_pos_node.outputs["Geometry"], sba)

    add_linear_gizmo(ng, "Radius Gizmo", group_in.outputs["Radius"],
                      combine_point(ng, x=group_in.outputs["Radius"]), const_vec(ng, (1, 0, 0)), "X")
    add_dial_gizmo(ng, "Subdivisions Gizmo", group_in.outputs["Subdivisions"],
                    combine_point(ng, z=group_in.outputs["Radius"]), const_vec(ng, (0, 0, 1)), "Z")

    return ng


def build_capsule_gn_group(name="[PrimLib] Capsule"):
    """Cylinder body with two hemispherical caps (top/bottom halves of a UV
    sphere, built the same sphere-minus-cutter way as the Dome), joined and
    welded at the seams with Merge by Distance."""
    sba = ensure_smooth_by_angle_group()
    ng = bpy.data.node_groups.new(name, "GeometryNodeTree")
    iface = ng.interface
    iface.new_socket(name="Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    iface.new_socket(name="Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")

    radius_in = iface.new_socket(name="Radius", in_out="INPUT", socket_type="NodeSocketFloat")
    radius_in.default_value = 1.0
    radius_in.min_value = 0.001
    height_in = iface.new_socket(name="Height", in_out="INPUT", socket_type="NodeSocketFloat")
    height_in.default_value = 2.0
    height_in.min_value = 0.001
    seg_in = iface.new_socket(name="Segments", in_out="INPUT", socket_type="NodeSocketInt")
    seg_in.default_value = 24
    seg_in.min_value = 3
    add_common_interface(iface, smooth_default=True)

    group_in = ng.nodes.new("NodeGroupInput")
    group_out = ng.nodes.new("NodeGroupOutput")

    half_height = half(ng, group_in.outputs["Height"])

    # Cylindrical body, no caps -- the two hemispheres provide the ends.
    cyl_node = ng.nodes.new("GeometryNodeMeshCylinder")
    cyl_node.fill_type = "NONE"
    ng.links.new(group_in.outputs["Segments"], cyl_node.inputs["Vertices"])
    ng.links.new(group_in.outputs["Radius"], cyl_node.inputs["Radius"])
    ng.links.new(group_in.outputs["Height"], cyl_node.inputs["Depth"])

    # Cutter cube, comfortably larger than the sphere, top face at Z=0.
    cutter_size = ng.nodes.new("ShaderNodeMath")
    cutter_size.operation = "MULTIPLY"
    cutter_size.inputs[1].default_value = 4.0
    ng.links.new(group_in.outputs["Radius"], cutter_size.inputs[0])
    half_cutter = half(ng, cutter_size.outputs["Value"])

    def hemisphere(keep_upper):
        sphere_node = ng.nodes.new("GeometryNodeMeshUVSphere")
        ng.links.new(group_in.outputs["Segments"], sphere_node.inputs["Segments"])
        sphere_node.inputs["Rings"].default_value = 16
        ng.links.new(group_in.outputs["Radius"], sphere_node.inputs["Radius"])

        cutter_node = ng.nodes.new("GeometryNodeMeshCube")
        ng.links.new(combine_point(ng, x=cutter_size.outputs["Value"], y=cutter_size.outputs["Value"],
                                    z=cutter_size.outputs["Value"]), cutter_node.inputs["Size"])
        cutter_tf = ng.nodes.new("GeometryNodeTransform")
        ng.links.new(cutter_node.outputs["Mesh"], cutter_tf.inputs["Geometry"])
        # Cutter must cover the half we DON'T want to keep (Dome's convention:
        # cutter below z=0 -> DIFFERENCE keeps the upper half).
        z_off = negate(ng, half_cutter) if keep_upper else half_cutter
        ng.links.new(combine_point(ng, z=z_off), cutter_tf.inputs["Translation"])

        diff_node = ng.nodes.new("GeometryNodeMeshBoolean")
        diff_node.operation = "DIFFERENCE"
        ng.links.new(sphere_node.outputs["Mesh"], diff_node.inputs[0])
        ng.links.new(cutter_tf.outputs["Geometry"], diff_node.inputs[1])
        return diff_node.outputs["Mesh"]

    top_dome = hemisphere(keep_upper=True)
    bottom_dome = hemisphere(keep_upper=False)

    top_tf = ng.nodes.new("GeometryNodeTransform")
    ng.links.new(top_dome, top_tf.inputs["Geometry"])
    ng.links.new(combine_point(ng, z=half_height), top_tf.inputs["Translation"])

    bottom_tf = ng.nodes.new("GeometryNodeTransform")
    ng.links.new(bottom_dome, bottom_tf.inputs["Geometry"])
    ng.links.new(combine_point(ng, z=negate(ng, half_height)), bottom_tf.inputs["Translation"])

    join = ng.nodes.new("GeometryNodeJoinGeometry")
    ng.links.new(cyl_node.outputs["Mesh"], join.inputs["Geometry"])
    ng.links.new(top_tf.outputs["Geometry"], join.inputs["Geometry"])
    ng.links.new(bottom_tf.outputs["Geometry"], join.inputs["Geometry"])

    merge_node = ng.nodes.new("GeometryNodeMergeByDistance")
    merge_node.inputs["Selection"].default_value = True
    merge_node.inputs["Distance"].default_value = 0.0001
    ng.links.new(join.outputs["Geometry"], merge_node.inputs["Geometry"])

    add_smooth_material_tail(ng, group_in, group_out, merge_node.outputs["Geometry"], sba)

    add_linear_gizmo(ng, "Radius Gizmo", group_in.outputs["Radius"],
                      combine_point(ng, x=group_in.outputs["Radius"]), const_vec(ng, (1, 0, 0)), "X")
    add_linear_gizmo(ng, "Height Gizmo", half_height,
                      combine_point(ng, z=group_in.outputs["Radius"], y=half_height), const_vec(ng, (0, 1, 0)), "Y")
    add_dial_gizmo(ng, "Segments Gizmo", group_in.outputs["Segments"],
                    combine_point(ng, x=negate(ng, group_in.outputs["Radius"])), const_vec(ng, (0, 0, 1)), "X")

    return ng


def build_gear_gn_group(name="[PrimLib] Gear"):
    """Simple cog/gear: a circle whose vertices alternate between Inner and
    Outer Radius (a zigzag ring, the classic cheap gear-silhouette trick),
    filled and extruded to Height."""
    sba = ensure_smooth_by_angle_group()
    ng = bpy.data.node_groups.new(name, "GeometryNodeTree")
    iface = ng.interface
    iface.new_socket(name="Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    iface.new_socket(name="Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")

    blades_in = iface.new_socket(name="Num Blades", in_out="INPUT", socket_type="NodeSocketInt")
    blades_in.default_value = 12
    blades_in.min_value = 3
    inner_in = iface.new_socket(name="Inner Radius", in_out="INPUT", socket_type="NodeSocketFloat")
    inner_in.default_value = 0.75
    inner_in.min_value = 0.001
    outer_in = iface.new_socket(name="Outer Radius", in_out="INPUT", socket_type="NodeSocketFloat")
    outer_in.default_value = 1.0
    outer_in.min_value = 0.001
    height_in = iface.new_socket(name="Height", in_out="INPUT", socket_type="NodeSocketFloat")
    height_in.default_value = 0.5
    height_in.min_value = 0.001
    add_common_interface(iface, smooth_default=False)

    group_in = ng.nodes.new("NodeGroupInput")
    group_out = ng.nodes.new("NodeGroupOutput")

    vert_count = ng.nodes.new("ShaderNodeMath")
    vert_count.operation = "MULTIPLY"
    vert_count.inputs[1].default_value = 2.0
    ng.links.new(group_in.outputs["Num Blades"], vert_count.inputs[0])

    circle_node = ng.nodes.new("GeometryNodeMeshCircle")
    circle_node.fill_type = "NGON"
    circle_node.inputs["Radius"].default_value = 1.0
    ng.links.new(vert_count.outputs["Value"], circle_node.inputs["Vertices"])

    index_node = ng.nodes.new("GeometryNodeInputIndex")
    is_odd = ng.nodes.new("ShaderNodeMath")
    is_odd.operation = "MODULO"
    is_odd.inputs[1].default_value = 2.0
    ng.links.new(index_node.outputs["Index"], is_odd.inputs[0])

    switch_node = ng.nodes.new("GeometryNodeSwitch")
    switch_node.input_type = "FLOAT"
    compare_node = ng.nodes.new("FunctionNodeCompare")
    compare_node.data_type = "FLOAT"
    compare_node.operation = "LESS_THAN"
    compare_node.inputs[1].default_value = 0.5
    ng.links.new(is_odd.outputs["Value"], compare_node.inputs[0])
    ng.links.new(compare_node.outputs["Result"], switch_node.inputs["Switch"])
    ng.links.new(group_in.outputs["Inner Radius"], switch_node.inputs["False"])
    ng.links.new(group_in.outputs["Outer Radius"], switch_node.inputs["True"])

    position_node = ng.nodes.new("GeometryNodeInputPosition")
    normalize_node = ng.nodes.new("ShaderNodeVectorMath")
    normalize_node.operation = "NORMALIZE"
    ng.links.new(position_node.outputs["Position"], normalize_node.inputs[0])
    scale_node = ng.nodes.new("ShaderNodeVectorMath")
    scale_node.operation = "SCALE"
    ng.links.new(normalize_node.outputs["Vector"], scale_node.inputs["Vector"])
    ng.links.new(switch_node.outputs[0], scale_node.inputs["Scale"])

    set_pos_node = ng.nodes.new("GeometryNodeSetPosition")
    ng.links.new(circle_node.outputs["Mesh"], set_pos_node.inputs["Geometry"])
    ng.links.new(scale_node.outputs["Vector"], set_pos_node.inputs["Position"])

    extrude_node = ng.nodes.new("GeometryNodeExtrudeMesh")
    extrude_node.mode = "FACES"
    ng.links.new(set_pos_node.outputs["Geometry"], extrude_node.inputs["Mesh"])
    ng.links.new(group_in.outputs["Height"], extrude_node.inputs["Offset Scale"])
    extrude_node.inputs["Offset"].default_value = (0.0, 0.0, 1.0)

    center_tf = ng.nodes.new("GeometryNodeTransform")
    ng.links.new(extrude_node.outputs["Mesh"], center_tf.inputs["Geometry"])
    ng.links.new(combine_point(ng, z=negate(ng, half(ng, group_in.outputs["Height"]))),
                  center_tf.inputs["Translation"])

    add_smooth_material_tail(ng, group_in, group_out, center_tf.outputs["Geometry"], sba)

    add_linear_gizmo(ng, "Outer Radius Gizmo", group_in.outputs["Outer Radius"],
                      combine_point(ng, x=group_in.outputs["Outer Radius"]), const_vec(ng, (1, 0, 0)), "X")
    add_linear_gizmo(ng, "Inner Radius Gizmo", group_in.outputs["Inner Radius"],
                      combine_point(ng, x=negate(ng, group_in.outputs["Inner Radius"])),
                      const_vec(ng, (-1, 0, 0)), "X")
    add_linear_gizmo(ng, "Height Gizmo", half(ng, group_in.outputs["Height"]),
                      combine_point(ng, z=half(ng, group_in.outputs["Height"])), const_vec(ng, (0, 0, 1)), "Z")
    add_dial_gizmo(ng, "Num Blades Gizmo", group_in.outputs["Num Blades"],
                    combine_point(ng, y=group_in.outputs["Outer Radius"]), const_vec(ng, (0, 0, 1)), "Y")

    return ng


def build_spring_gn_group(name="[PrimLib] Spring"):
    """Coil spring: a helix path built point-by-point (no native spiral
    curve primitive) via a Mesh Line + index-driven trig math, converted to
    a curve and swept with a small profile circle via Curve to Mesh."""
    sba = ensure_smooth_by_angle_group()
    ng = bpy.data.node_groups.new(name, "GeometryNodeTree")
    iface = ng.interface
    iface.new_socket(name="Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    iface.new_socket(name="Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")

    bottom_in = iface.new_socket(name="Bottom Radius", in_out="INPUT", socket_type="NodeSocketFloat")
    bottom_in.default_value = 1.0
    bottom_in.min_value = 0.001
    top_in = iface.new_socket(name="Top Radius", in_out="INPUT", socket_type="NodeSocketFloat")
    top_in.default_value = 1.0
    top_in.min_value = 0.001
    height_in = iface.new_socket(name="Height", in_out="INPUT", socket_type="NodeSocketFloat")
    height_in.default_value = 2.0
    height_in.min_value = 0.001
    rotations_in = iface.new_socket(name="Rotations", in_out="INPUT", socket_type="NodeSocketFloat")
    rotations_in.default_value = 6.0
    rotations_in.min_value = 0.25
    ring_radius_in = iface.new_socket(name="Ring Radius", in_out="INPUT", socket_type="NodeSocketFloat")
    ring_radius_in.default_value = 0.1
    ring_radius_in.min_value = 0.001
    div_circle_in = iface.new_socket(name="Div Circle", in_out="INPUT", socket_type="NodeSocketInt")
    div_circle_in.default_value = 256
    div_circle_in.min_value = 8
    div_ring_in = iface.new_socket(name="Div Ring", in_out="INPUT", socket_type="NodeSocketInt")
    div_ring_in.default_value = 8
    div_ring_in.min_value = 3
    add_common_interface(iface, smooth_default=True)

    group_in = ng.nodes.new("NodeGroupInput")
    group_out = ng.nodes.new("NodeGroupOutput")

    line_node = ng.nodes.new("GeometryNodeMeshLine")
    line_node.mode = "OFFSET"
    line_node.count_mode = "TOTAL"
    ng.links.new(group_in.outputs["Div Circle"], line_node.inputs["Count"])

    count_minus1 = ng.nodes.new("ShaderNodeMath")
    count_minus1.operation = "SUBTRACT"
    count_minus1.inputs[1].default_value = 1.0
    count_f = ng.nodes.new("ShaderNodeMath")
    count_f.operation = "MULTIPLY"
    count_f.inputs[1].default_value = 1.0
    ng.links.new(group_in.outputs["Div Circle"], count_f.inputs[0])
    ng.links.new(count_f.outputs["Value"], count_minus1.inputs[0])

    index_node = ng.nodes.new("GeometryNodeInputIndex")
    index_f = ng.nodes.new("ShaderNodeMath")
    index_f.operation = "MULTIPLY"
    index_f.inputs[1].default_value = 1.0
    ng.links.new(index_node.outputs["Index"], index_f.inputs[0])

    t_node = ng.nodes.new("ShaderNodeMath")
    t_node.operation = "DIVIDE"
    ng.links.new(index_f.outputs["Value"], t_node.inputs[0])
    ng.links.new(count_minus1.outputs["Value"], t_node.inputs[1])

    angle_node = ng.nodes.new("ShaderNodeMath")
    angle_node.operation = "MULTIPLY"
    ng.links.new(t_node.outputs["Value"], angle_node.inputs[0])
    rot_turns = ng.nodes.new("ShaderNodeMath")
    rot_turns.operation = "MULTIPLY"
    rot_turns.inputs[1].default_value = 2.0 * math.pi
    ng.links.new(group_in.outputs["Rotations"], rot_turns.inputs[0])
    ng.links.new(rot_turns.outputs["Value"], angle_node.inputs[1])

    cos_node = ng.nodes.new("ShaderNodeMath")
    cos_node.operation = "COSINE"
    ng.links.new(angle_node.outputs["Value"], cos_node.inputs[0])
    sin_node = ng.nodes.new("ShaderNodeMath")
    sin_node.operation = "SINE"
    ng.links.new(angle_node.outputs["Value"], sin_node.inputs[0])

    radius_lerp = ng.nodes.new("ShaderNodeMix")
    radius_lerp.data_type = "FLOAT"
    radius_lerp.clamp_factor = True
    ng.links.new(t_node.outputs["Value"], radius_lerp.inputs["Factor"])
    ng.links.new(group_in.outputs["Bottom Radius"], radius_lerp.inputs["A"])
    ng.links.new(group_in.outputs["Top Radius"], radius_lerp.inputs["B"])

    x_node = ng.nodes.new("ShaderNodeMath")
    x_node.operation = "MULTIPLY"
    ng.links.new(cos_node.outputs["Value"], x_node.inputs[0])
    ng.links.new(radius_lerp.outputs["Result"], x_node.inputs[1])
    y_node = ng.nodes.new("ShaderNodeMath")
    y_node.operation = "MULTIPLY"
    ng.links.new(sin_node.outputs["Value"], y_node.inputs[0])
    ng.links.new(radius_lerp.outputs["Result"], y_node.inputs[1])

    z_node = ng.nodes.new("ShaderNodeMath")
    z_node.operation = "MULTIPLY"
    ng.links.new(t_node.outputs["Value"], z_node.inputs[0])
    ng.links.new(group_in.outputs["Height"], z_node.inputs[1])
    z_centered = ng.nodes.new("ShaderNodeMath")
    z_centered.operation = "SUBTRACT"
    ng.links.new(z_node.outputs["Value"], z_centered.inputs[0])
    ng.links.new(half(ng, group_in.outputs["Height"]), z_centered.inputs[1])

    pos_combine = ng.nodes.new("ShaderNodeCombineXYZ")
    ng.links.new(x_node.outputs["Value"], pos_combine.inputs["X"])
    ng.links.new(y_node.outputs["Value"], pos_combine.inputs["Y"])
    ng.links.new(z_centered.outputs["Value"], pos_combine.inputs["Z"])

    set_pos_node = ng.nodes.new("GeometryNodeSetPosition")
    ng.links.new(line_node.outputs["Mesh"], set_pos_node.inputs["Geometry"])
    ng.links.new(pos_combine.outputs["Vector"], set_pos_node.inputs["Position"])

    to_points = ng.nodes.new("GeometryNodeMeshToPoints")
    ng.links.new(set_pos_node.outputs["Geometry"], to_points.inputs["Mesh"])

    to_curve = ng.nodes.new("GeometryNodePointsToCurves")
    ng.links.new(to_points.outputs["Points"], to_curve.inputs["Points"])

    profile_circle = ng.nodes.new("GeometryNodeCurvePrimitiveCircle")
    profile_circle.mode = "RADIUS"
    ng.links.new(group_in.outputs["Ring Radius"], profile_circle.inputs["Radius"])
    ng.links.new(group_in.outputs["Div Ring"], profile_circle.inputs["Resolution"])

    c2m = ng.nodes.new("GeometryNodeCurveToMesh")
    c2m.inputs["Fill Caps"].default_value = True
    ng.links.new(to_curve.outputs["Curves"], c2m.inputs["Curve"])
    ng.links.new(profile_circle.outputs["Curve"], c2m.inputs["Profile Curve"])

    add_smooth_material_tail(ng, group_in, group_out, c2m.outputs["Mesh"], sba)

    add_linear_gizmo(ng, "Bottom Radius Gizmo", group_in.outputs["Bottom Radius"],
                      combine_point(ng, x=group_in.outputs["Bottom Radius"],
                                    z=negate(ng, half(ng, group_in.outputs["Height"]))),
                      const_vec(ng, (1, 0, 0)), "X")
    add_linear_gizmo(ng, "Top Radius Gizmo", group_in.outputs["Top Radius"],
                      combine_point(ng, x=group_in.outputs["Top Radius"],
                                    z=half(ng, group_in.outputs["Height"])),
                      const_vec(ng, (1, 0, 0)), "X")
    add_linear_gizmo(ng, "Height Gizmo", half(ng, group_in.outputs["Height"]),
                      combine_point(ng, z=half(ng, group_in.outputs["Height"])), const_vec(ng, (0, 0, 1)), "Z")
    add_linear_gizmo(ng, "Ring Radius Gizmo", group_in.outputs["Ring Radius"],
                      combine_point(ng, x=negate(ng, group_in.outputs["Bottom Radius"])),
                      const_vec(ng, (0, 0, 1)), "PRIMARY")
    add_dial_gizmo(ng, "Rotations Gizmo", group_in.outputs["Rotations"],
                    combine_point(ng, y=group_in.outputs["Bottom Radius"],
                                  z=negate(ng, half(ng, group_in.outputs["Height"]))),
                    const_vec(ng, (0, 0, 1)), "Y")

    return ng


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

    # obj.bound_box is stale (zero-size) until the depsgraph has evaluated the
    # object at least once — matters for GN-modifier objects (Cube), whose base
    # mesh has no geometry of its own to fall back on.
    obj.update_tag(refresh={"DATA"})
    bpy.context.view_layer.update()

    bbox = [obj.matrix_world @ mathutils.Vector(c) for c in obj.bound_box]
    center = sum(bbox, mathutils.Vector((0, 0, 0))) / 8
    radius = max((v - center).length for v in bbox) or 1.0

    cam_dir = mathutils.Vector((1.6, -1.8, 1.3)).normalized()
    cam.location = center + cam_dir * radius * 3.4
    cam.rotation_euler = (center - cam.location).to_track_quat("-Z", "Y").to_euler()

    key.location = cam.location + mathutils.Vector((-1.0, -1.5, 2.0))
    key.rotation_euler = (center - key.location).to_track_quat("-Z", "Y").to_euler()

    # Pass 1: shaded render with the random-hue preview material — the
    # shipped asset keeps its neutral clay material.
    preview_bsdf.inputs["Base Color"].default_value = color
    restore_material = swap_material(obj, preview_mat)
    obj.update_tag(refresh={"DATA"})

    scene.render.filepath = filepath
    bpy.ops.render.render(write_still=True)

    restore_material()

    # Pass 2: a duplicate with its mesh REPLACED by a Wireframe modifier
    # (use_replace=True — pure edge tubes, no original faces), so there is
    # only one material in play and no legacy material_offset/slot juggling
    # against Geometry Nodes' own material handling (which doesn't line up
    # with the traditional per-face material_index system). Composited over
    # pass 1 with numpy (Blender's bundled Python has no Pillow).
    wire_path = filepath + ".wire.png"
    dup = obj.copy()
    dup.data = obj.data.copy()
    scene.collection.objects.link(dup)
    obj.hide_render = True

    wire_mod = dup.modifiers.new("Preview Wire", "WIREFRAME")
    wire_mod.thickness = 0.012
    wire_mod.use_replace = True
    restore_wire_material = swap_material(dup, preview_wire_mat)
    dup.update_tag(refresh={"DATA"})

    scene.render.filepath = wire_path
    bpy.ops.render.render(write_still=True)

    restore_wire_material()
    bpy.data.objects.remove(dup, do_unlink=True)
    obj.hide_render = False
    obj.update_tag(refresh={"DATA"})

    base_img = bpy.data.images.load(filepath)
    wire_img = bpy.data.images.load(wire_path)
    w, h = base_img.size
    base_px = np.array(base_img.pixels[:], dtype=np.float32).reshape(h, w, 4)
    wire_px = np.array(wire_img.pixels[:], dtype=np.float32).reshape(h, w, 4)
    wa = wire_px[:, :, 3:4]
    out = wire_px * wa + base_px * (1.0 - wa)
    out[:, :, 3:4] = wa + base_px[:, :, 3:4] * (1.0 - wa)

    base_img.pixels[:] = out.flatten().tolist()
    base_img.filepath_raw = filepath
    base_img.file_format = "PNG"
    base_img.save()
    bpy.data.images.remove(base_img)
    bpy.data.images.remove(wire_img)
    os.remove(wire_path)

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
    # -- Base primitives (all parametric: Geometry Nodes modifier + native
    # viewport gizmos, no fixed mesh) -----------------------------------------
    dict(
        name="Cube", category="base",
        make=lambda: make_gn_object("Cube", build_cube_gn_group()),
        shading=None, bevel=None, gn=True,
        description="Parametric cube — Size/Division/pivot are live modifier "
                    "inputs with viewport drag gizmos, not a fixed mesh.",
        tags=["cube", "box", "primitive", "parametric"],
    ),
    dict(
        name="Sphere", category="base",
        make=lambda: make_gn_object("Sphere", build_sphere_gn_group()),
        shading=None, bevel=None, gn=True,
        description="Parametric UV sphere — Radius/Segments/Rings are live "
                    "modifier inputs with viewport drag gizmos.",
        tags=["sphere", "ball", "primitive", "parametric"],
    ),
    dict(
        name="Ico Sphere", category="base",
        make=lambda: make_gn_object("Ico Sphere", build_icosphere_gn_group()),
        shading=None, bevel=None, gn=True,
        description="Parametric icosphere — Radius/Subdivisions are live "
                    "modifier inputs with viewport drag gizmos.",
        tags=["sphere", "ico", "primitive", "parametric"],
    ),
    dict(
        name="Cylinder", category="base",
        make=lambda: make_gn_object("Cylinder", build_cylinder_gn_group()),
        shading=None, bevel=None, gn=True,
        description="Parametric cylinder — Radius/Depth/Vertices are live "
                    "modifier inputs with viewport drag gizmos.",
        tags=["cylinder", "primitive", "parametric"],
    ),
    dict(
        name="Cone", category="base",
        make=lambda: make_gn_object("Cone", build_cone_gn_group()),
        shading=None, bevel=None, gn=True,
        description="Parametric cone — Radius Top/Bottom, Depth, Vertices are "
                    "live modifier inputs with viewport drag gizmos.",
        tags=["cone", "primitive", "parametric"],
    ),
    dict(
        name="Torus", category="base",
        make=lambda: make_gn_object("Torus", build_torus_gn_group()),
        shading=None, bevel=None, gn=True,
        description="Parametric torus — Major/Minor Radius and Segments are "
                    "live modifier inputs with viewport drag gizmos.",
        tags=["torus", "donut", "primitive", "parametric"],
    ),
    dict(
        name="Plane", category="base",
        make=lambda: make_gn_object("Plane", build_plane_gn_group()),
        shading=None, bevel=None, gn=True,
        description="Parametric plane/grid — Size X/Y and Division X/Y are "
                    "live modifier inputs with viewport drag gizmos.",
        tags=["plane", "grid", "primitive", "parametric"],
    ),
    dict(
        name="Quad Sphere", category="base",
        make=lambda: make_gn_object("Quad Sphere", build_quad_sphere_gn_group()),
        shading=None, bevel=None, gn=True,
        description="Parametric cube-sphere — Radius/Subdivisions are live "
                    "modifier inputs with viewport drag gizmos. Even quad "
                    "topology, no poles, unlike a UV sphere.",
        tags=["sphere", "quad", "cube-sphere", "primitive", "parametric"],
    ),
    dict(
        name="Capsule", category="base",
        make=lambda: make_gn_object("Capsule", build_capsule_gn_group()),
        shading=None, bevel=None, gn=True,
        description="Parametric capsule — Radius/Height/Segments are live "
                    "modifier inputs with viewport drag gizmos.",
        tags=["capsule", "pill", "primitive", "parametric"],
    ),
    # -- Hard-surface kit -----------------------------------------------------
    dict(
        name="Rounded Cube", category="kit",
        make=lambda: make_gn_object("Rounded Cube", build_rounded_cube_gn_group()),
        shading=None, bevel=None, gn=True,
        description="Parametric rounded cube — Size and the Bevel Width/Segments "
                    "are live modifier inputs with viewport drag gizmos.",
        tags=["cube", "rounded", "kit", "hard-surface", "parametric"],
    ),
    dict(
        name="Tube", category="kit",
        make=lambda: make_gn_object("Tube", build_tube_gn_group()),
        shading=None, bevel=None, gn=True,
        description="Parametric hollow tube — Outer/Inner Radius, Height and "
                    "Div Circle are live modifier inputs with viewport drag gizmos.",
        tags=["tube", "pipe", "hollow", "kit", "hard-surface", "parametric"],
    ),
    dict(
        name="Dome", category="kit",
        make=lambda: make_gn_object("Dome", build_dome_gn_group()),
        shading=None, bevel=None, gn=True,
        description="Parametric half-sphere dome, flat base — Radius/Segments/Rings "
                    "are live modifier inputs with viewport drag gizmos.",
        tags=["dome", "half-sphere", "kit", "hard-surface", "parametric"],
    ),
    dict(
        name="Wedge", category="kit",
        make=lambda: make_gn_object("Wedge", build_wedge_gn_group()),
        shading=None, bevel=None, gn=True,
        description="Parametric ramp / wedge block — Width/Depth/Height and the "
                    "Bevel Width/Segments are live modifier inputs with viewport "
                    "drag gizmos.",
        tags=["wedge", "ramp", "kit", "hard-surface", "parametric"],
    ),
    dict(
        name="Stairs", category="kit",
        make=lambda: make_gn_object("Stairs", build_stairs_gn_group()),
        shading=None, bevel=None, gn=True,
        description="Parametric staircase — Width/Depth/Height/Steps are live "
                    "modifier inputs with viewport drag gizmos.",
        tags=["stairs", "steps", "kit", "hard-surface", "parametric"],
    ),
    dict(
        name="Pyramid", category="kit",
        make=lambda: make_gn_object("Pyramid", build_pyramid_gn_group()),
        shading=None, bevel=None, gn=True,
        description="Parametric square pyramid — Base Size/Height are live "
                    "modifier inputs with viewport drag gizmos.",
        tags=["pyramid", "kit", "hard-surface", "parametric"],
    ),
    dict(
        name="Hex Prism", category="kit",
        make=lambda: make_gn_object("Hex Prism", build_hex_prism_gn_group()),
        shading=None, bevel=None, gn=True,
        description="Parametric N-gon prism (default hexagon) — Radius/Depth/"
                    "Vertices and the Bevel Width/Segments are live modifier "
                    "inputs with viewport drag gizmos.",
        tags=["hexagon", "prism", "kit", "hard-surface", "parametric"],
    ),
    dict(
        name="Gear", category="kit",
        make=lambda: make_gn_object("Gear", build_gear_gn_group()),
        shading=None, bevel=None, gn=True,
        description="Parametric gear/cog — Num Blades, Inner/Outer Radius and "
                    "Height are live modifier inputs with viewport drag gizmos.",
        tags=["gear", "cog", "mechanical", "kit", "hard-surface", "parametric"],
    ),
    dict(
        name="Spring", category="kit",
        make=lambda: make_gn_object("Spring", build_spring_gn_group()),
        shading=None, bevel=None, gn=True,
        description="Parametric coil spring — Bottom/Top Radius, Height, "
                    "Rotations and Ring Radius are live modifier inputs with "
                    "viewport drag gizmos.",
        tags=["spring", "coil", "mechanical", "kit", "hard-surface", "parametric"],
    ),
]


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
