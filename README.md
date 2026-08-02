# Primitive Assets Library

A free **Blender Asset Library** of clean, ready-to-drag primitive shapes and a small
hard-surface kit — the same idea as *Modern Primitives* / *ND Primitives*, but shipped
as an **Asset Browser library** instead of an add-on. No Python, no operators: just a
`.blend` file with everything already marked as an asset, tagged, catalogued and
thumbnailed.

![Preview](docs/contact_sheet.png)

## What's inside

One file, `assets/primitives.blend`, containing 14 assets in two catalogs:

**Base** — the classic primitives, all parametric (see below)
- Cube, Sphere, Ico Sphere, Cylinder, Cone, Torus, Plane

**Hard Surface Kit** — kitbash-ready pieces, most of them parametric too
- Rounded Cube, Tube (hollow cylinder), Dome (half-sphere), Wedge, Stairs, Pyramid, Hex Prism

Every asset has a rendered preview thumbnail (shaded + wireframe overlay, so topology
reads at a glance), a description and search tags, and lives in its catalog so it
shows up correctly in the Asset Browser's catalog tree.

### Parametric primitives

11 of the 14 shapes ship as plain **Object assets** — no Collection wrapper, no
child Empties, nothing extra to bring along when you drag one into a scene. Each
one is an empty-mesh object driving a Geometry Nodes modifier (built by a
`build_<shape>_gn_group()` function in `scripts/build_library.py`) that exposes
its dimensions as native viewport gizmos:

**Base**
- **Cube** — Size X/Y/Z (arrow gizmos), Division X/Y/Z (ring gizmos), Corner
  Ratio (a translate-only gizmo that moves the pivot anywhere from center to a
  corner), Smooth / Smooth Angle, Material
- **Sphere** — Radius, Segments, Rings
- **Ico Sphere** — Radius, Subdivisions
- **Cylinder** — Radius, Depth, Vertices
- **Cone** — Radius Bottom, Radius Top, Depth, Vertices
- **Torus** — Major Radius, Minor Radius, Major Segments, Minor Segments (built
  by sweeping a profile circle along a path circle with `Curve to Mesh` — there's
  no native Torus primitive node in Geometry Nodes)
- **Plane** — Size X/Y, Division X/Y

**Hard Surface Kit**
- **Rounded Cube** — Size X/Y/Z, Bevel Width, Bevel Segments (a `Mesh Cube` +
  the `Mesh Bevel` node, replacing the old fixed Bevel modifier)
- **Dome** — Radius, Segments, Rings (a UV Sphere cut flat by a Boolean
  `DIFFERENCE` against a cutter cube — see note below)
- **Wedge** — Width, Depth, Height, Bevel Width, Bevel Segments (swept from a
  triangular profile curve along a straight path — no native wedge/ramp
  primitive either)
- **Hex Prism** — Radius, Depth, Vertices (defaults to 6 — set it to anything
  to get any N-gon prism), Bevel Width, Bevel Segments

Tube, Stairs and Pyramid are still fixed meshes (not converted in this pass).

Every parametric shape also has Smooth / Smooth Angle (via Blender's bundled
*Smooth by Angle* node group) and a swappable Material input.

> **Boolean node gotcha:** this Blender build's `Mesh Boolean` node silently
> returns its second input **unmodified** for `INTERSECT`/`UNION` — a solver
> bug/limitation confirmed by testing plain cube-vs-cube — while `DIFFERENCE`
> (Mesh 1 − Mesh 2) works correctly and cleanly caps the cut. The Dome uses
> `DIFFERENCE` (sphere minus a cutter covering the unwanted lower half) instead
> of the more obvious `INTERSECT`, precisely to route around this.

The gizmos are plain node-group *data* (`GeometryNodeGizmoLinear` /
`GeometryNodeGizmoDial` / `GeometryNodeGizmoTransform`, color-coded per axis), the
same mechanism *Modern Primitives*/*ND Primitives* use internally — no add-on
needed, and because each shape is a straight Object asset (not a Collection),
drag-and-drop from the Asset Browser works exactly like any other asset. Blender's
native dial gizmo has no built-in "which way does turning it increase the value"
marker — there isn't a clean way to add one without extra geometry or child
objects riding along on drag-and-drop, so these ship without one; the direction
convention is a consistent right-hand-rule per axis across all shapes once you
turn it once.

## Installing it as an Asset Library

There are two ways to hook this up in Blender, depending on your version.

### Option A — Remote Asset Library (Blender 5.2+, no download step)

Blender 5.2 added genuine remote asset libraries: point it at a URL and it fetches
the catalog listing, thumbnails and `.blend` data on demand, no `git clone` required.
This repo ships the `_asset-library-meta.json` / `_v1/` index that format needs,
generated straight from `primitives.blend` (see below), so you can add it as:

```python
import bpy
bpy.ops.preferences.asset_library_add(
    remote_url="https://raw.githubusercontent.com/pesaksintondji/primitive-assets-library/master/assets/",
    type='REMOTE',
)
```

Run that once in Blender's Python console (or `Scripting` tab), then check
**Edit ▸ Preferences ▸ File Paths ▸ Asset Libraries** — a *Primitive Assets Library*
entry should appear, marked as a remote (globe icon) library.

> The URL has to point at the folder that directly contains
> `_asset-library-meta.json` — that's `.../primitive-assets-library/master/assets/`,
> not the repo root, and not the `github.com` page (which serves HTML, not raw
> files — that's the mistake that produces a "file does not exist ... meta.json"
> error).

### Option B — Local folder library (any Blender version with Asset Browser)

1. Get the repo onto your disk — either clone it:

   ```bash
   git clone https://github.com/pesaksintondji/primitive-assets-library.git
   ```

   or, if you just want the single `.blend` file, download it directly from its raw
   GitHub URL:

   ```bash
   curl -L -o primitives.blend \
     https://raw.githubusercontent.com/pesaksintondji/primitive-assets-library/master/assets/primitives.blend
   ```

   (Grab `blender_assets.cats.txt` from the same `assets/` folder too if you want the
   catalog names/tree to resolve — Blender falls back to "Unassigned" without it.)

2. In Blender: **Edit ▸ Preferences ▸ File Paths ▸ Asset Libraries ▸ +**
3. Name it (e.g. *Primitives*) and point the path at the `assets/` folder (the one
   containing `primitives.blend` and `blender_assets.cats.txt`) — if you only
   downloaded the loose `.blend`, point it at whatever folder you saved it in instead.
4. Open the Asset Browser (or the Asset Shelf in the 3D Viewport), pick your new
   library from the source dropdown, and drag any shape straight into your scene.

Update later with `git pull` — Blender picks up changes to the library folder
automatically, no re-linking needed.

## Regenerating the library

The whole `.blend` is generated by one script, so nothing here was hand-authored or
needs a GUI session to edit:

```bash
blender --background --python scripts/build_library.py
```

This rebuilds every mesh, re-applies shading/bevels, re-renders each preview thumbnail
and re-marks everything as an asset with the same catalog UUIDs — safe to re-run any
time, e.g. after editing `scripts/build_library.py` to add a new shape or tweak a
dimension.

To add a new asset: append a `dict(...)` entry to the `ASSETS` list in
`scripts/build_library.py` (mesh builder callable, category, shading mode, optional
bevel, description, tags) and re-run the script.

After that, regenerate the remote index (Option A above reads this, not the raw
`.blend`) so it picks up the new/changed assets and thumbnails:

```bash
./scripts/generate_remote_index.sh
```

It shells out to `blender -c asset_listing generate assets`, which re-scans
`primitives.blend` and rewrites `_asset-library-meta.json`, `_v1/*.json` and the
per-asset `.webp` thumbnails in `assets/primitives_thumbnails/`. It preserves the
library `name`/`contact` you've set in `_asset-library-meta.json` across re-runs.

## License

Assets and scripts are released under [CC0 1.0](LICENSE) — public domain, use them in
anything, no attribution required.
