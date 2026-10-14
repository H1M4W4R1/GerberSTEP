# GerberSTEP
<div align="center">
  <img src="examples/screenshot.png" alt="Preview screenshot"/>
</div>

A PyQt6 desktop app that turns a Gerber fabrication set into a coloured STEP
assembly with separate copper, dielectric, soldermask and silkscreen components.

## Run on this machine

Double-click **launch.bat**. The local `.venv` already contains the dependencies.

1. Choose **Open folder** and select `examples/demo` to try the included board.
2. Choose colors and finish; apply a compatible JLCPCB preset or edit layer thicknesses.
3. Choose **Export STEP assembly**.

You can also run `.venv\Scripts\python.exe main.py examples\demo` from this folder.

## Fresh installation

Use Python **3.12, 64-bit** (the tested runtime). CadQuery includes a large native
CAD dependency, so the first installation downloads several hundred megabytes.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[test]"
.\.venv\Scripts\python.exe main.py
```

On Linux/macOS, use `python3.12 -m venv .venv` and `.venv/bin/python` instead.
The UI uses Qt's native window system; a functioning desktop session is required.

## Layer controls

| Material | Default | Controls |
| --- | --- | --- |
| Copper | 0.100 mm per foil | Thickness input and checkbox beside each foil |
| Dielectric | 1.600 mm total initially | Separate thickness input and checkbox for each insulating section |
| Soldermask | 0.100 mm per layer | Individual top/bottom checkbox and thickness |
| Silkscreen | 0.100 mm per layer | Individual top/bottom checkbox and thickness |

Dielectric thickness means **total insulating material**, excluding all copper.
The layer list runs from top to bottom, with copper and dielectric controls beside
their layers. For multilayer boards, dielectric sections initially share 1.600 mm
(rounded to 0.0001 mm); each section can then have a different thickness.
Dielectric sections are numbered from bottom to top. Changes update the preview
and STEP stack heights and survive precision rebuilds.
A two-sided board with the defaults has a 2.2 mm overall
stack: 1.6 mm substrate plus 0.1 mm each for two copper, two mask and two silk
layers. Missing surface files do not create artificial layers.

Left-click **Soldermask** or **Silkscreen** in the legend to choose colors for both
sides in the 2D/3D preview and STEP assembly. Left-click **Copper** for the board
finish menu, offering bare copper, silver HASL,
and gold ENIG. Finish colors the entire outer copper component; internal copper
stays copper-colored. This is an appearance approximation, without additional
plating geometry or thickness. The manufacturing monolith retains its own color.

Select a compatible **JLCPCB** preset and press its adjacent refresh icon to
fill all copper and dielectric inputs at once. Layer visibility and coating
thicknesses stay unchanged, and every value remains editable. Preset selection
alone does not change thicknesses. Values and appearance survive precision rebuilds.

Included presets are nominal two-layer boards (0.4–2.0 mm, 35 µm outer copper)
and four-layer JLC04161H-7628, -3313, -1080 and -2116 stacks, using
[JLCPCB's published stackup dimensions](https://jlcpcb.com/impedance)
(checked October 14, 2026). Two-layer dielectric thickness is estimated as nominal
thickness minus both copper foils. Four-layer dimensions retain the published
values, including 15.2 µm inner copper; their sums can differ from nominal 1.6 mm.
Coatings add to the displayed height. Presets match imported copper layers,
including hidden ones; other layer counts use manual values. No stackup is
inferred from Gerber artwork, and this is not JLCPCB's complete catalog.

Use the pencil to the left of the board name to edit the suggested STEP filename.
ZIP imports use the ZIP filename, without its extension. Renaming does not change
the source files, and survives precision rebuilds.

Every material can be disabled in the layer list, including copper and dielectric.
For a silk-only export, leave only the desired silkscreen checked. Disabling core
materials preserves the board's layer heights. An empty selection disables export.

**Align coatings with copper** moves exported mask and silk to the same substrate surface
plane as outer copper. Top coatings extend upward and bottom coatings downward.
Their own thicknesses are retained, so solids can overlap in this mode. It is
intended for the requested machining workflow. The preview always keeps coatings
stacked, regardless of this export-only option. STEP components stay separate.

## Precision and manufacturing body

**Curve precision** controls the maximum chord error used to approximate circles
and arcs in the outline, artwork and drill holes. It affects both preview and
export geometry, not just display quality. Round Excellon drill holes are an
exception: STEP always exports their exact diameters with cylindrical walls,
independent of preview precision, so CAM software can recognize them for drilling.

STEP also restores circular edges on round pads, trace ends and other supported
source arcs when consecutive boundary vertices match the original Gerber circle.
It uses source centres and radii, rather than guessing curves from arbitrary
polygons. Clipped or ambiguous fragments retain their facets. Recovery is skipped
where it would create an invalid solid or connect separate material islands.
The preview remains polygonized; restored edges stay within the selected chord
tolerance of that preview.

This reduces the edges and faces that Fusion must select and process for pockets.
At Medium precision, the demo's manufacturing body drops from **525 to 307 faces**
(42% fewer), without reducing precision or removing trace detail. This is a model
complexity measurement, not a measured Fusion toolpath speedup. Re-export and
re-import existing boards to use the recovered arcs.

| Preset | Chord error | Intended trade-off |
| --- | --- | --- |
| Low | 0.10 mm | Fewest faces and simplest machining paths |
| Medium (default) | 0.05 mm | Balance of curve accuracy and face count |
| High | 0.01 mm | Original accuracy; most faces |

Changing precision rebuilds the open fabrication set in the background. Thickness,
enabled layers, coating alignment and camera position are preserved. Larger chord
errors visibly facet small holes and pads in the preview; unresolved curves also
remain faceted in export. Choose the tolerance your job permits.

Export automatically adds an extra component
named `Manufacturing_Monolith`, containing one Boolean-fused copper/dielectric solid.
It retains copper trace relief, outline cutouts and drill holes. Mask and silk are
excluded. The original material components remain in the same STEP assembly.

For machining, select `Manufacturing_Monolith` and hide the original layer components
so the overlapping duplicates are not part of your machining model. The preview
continues to show the material layers, without drawing a duplicate over them.
In Fusion's Drill operation, select a cylindrical hole wall on this body and use
**Select Same Diameter** as needed. Files exported before analytic drill support
must be re-exported and imported again; increasing precision alone does not turn
their flat hole faces into cylinders.
Disconnected boards
or unconnected stacks cannot form one monolith; the app reports an error rather than
silently exporting a multi-solid compound as a monolith. Fusion adds export time,
particularly at High precision.
If the selection does not contain both copper and dielectric, no monolith is
exported. It never restores layers you disabled.

## Preview

Switch between **3D** (drag to orbit, middle-drag to pan, scroll to zoom) and
**2D** (top or mirrored bottom view).
Double-click or press **Fit** to reset the camera. **Explode** separates layers
only in the preview and never changes export heights. The desktop 3D renderer
uses OpenGL with retained mesh buffers: rotation updates camera matrices, while
thickness and exploded-view changes update component transforms. Geometry and
colours are uploaded only when a material mesh changes. A working OpenGL driver
is required for interactive 3D. Headless screenshot tests use the software path.

Both previews use the same planar geometry and layer settings as the STEP
export, except for the export-only coating alignment, restored source arcs and
exact cylindrical drill walls. Loading, geometry preparation and
STEP writing run in a worker thread. Controls are locked while a job runs; the
window waits for that job before allowing closure.

## Input and geometry assumptions

- Open a folder or ZIP containing **one board**. Selecting an individual Gerber
  loads companion files from its folder. Drag-and-drop is also supported.
- Standard Gerber naming is detected by Gerbonara, including `.gtl/.gbl`,
  `.gts/.gbs`, `.gto/.gbo`, `.gko` and KiCad layer names. Unrecognized naming needs
  standard filenames; there is no manual layer mapping UI yet. Review **Import
  details** for parser warnings and recognized source files.
- Outline recovery bridges uniquely paired open endpoints up to **0.05 mm** apart,
  independently of curve precision. Intersections and duplicate edges are resolved
  into closed contours. If no closed contour exists, overlapping edge strokes are
  snapped within the smallest outline aperture width (at most **0.5 mm**), accepted
  only when all lines form closed contours. This supports slightly misaligned
  EasyEDA outline strokes. Remaining open lines are ignored only when a closed board
  boundary exists; **Import details** reports repairs and ignored lines. Review the
  preview before export: open cutouts can be missing. Larger gaps with no closed
  boundary still require a corrected outline Gerber. Closed outline cutouts and
  Excellon through holes and routed slots are subtracted from the material layers.
  Blind/buried via depths, plated barrels, edge plating, components,
  solder paste and fabrication drawings are not modeled.
- Standard soldermask Gerbers represent **openings**, so mask material is their
  complement within the board. Material-positive mask files must be inverted
  upstream. Legacy `%IPNEG*%` files are rejected; use a modern RS-274X export.
- Artwork, outlines and routed slots are polygonized with the **selected chord
  tolerance**. Supported source arcs are restored conservatively during STEP
  export. Round Excellon drills retain their source centres and radii and
  are cut as exact cylinders in every exported layer and the manufacturing body.
  This is a geometric reconstruction, not recovery of a manufacturer's stackup.

The assembly has one named, coloured component per material layer or dielectric
section. Disconnected copper islands remain separate solids inside that layer's
compound. Export validates each solid and writes through a temporary file so a
failed CAD operation does not replace an existing destination file.
The manufacturing monolith is an additional fused component when copper and dielectric are selected.

## Validation

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Tests cover Gerber polarity and aperture holes, arcs, outline cutouts, drills,
ZIP and companion-file loading, stack heights, optional layers, multilayer
ordering, Qt controls and asynchronous import. STEP is reopened through
OpenCascade and checked for solid validity, dimensions, names and volume.
Fixtures are synthetic; production fabrication sets still need comparison with
their original board designs.

`scripts/create_demo.py` regenerates the demonstration fabrication files.
`scripts/capture_preview.py` renders the actual Qt window to `output/` for visual
inspection. Windows offscreen rendering explicitly loads system Arial because
that backend does not enumerate system fonts automatically.

`scripts/benchmark_gpu.py` opens a brief native test window and records rotation
latency and mesh-upload counts in `output/gpu-benchmark.json`. The demo measured
4.17 ms median and 4.33 ms at the 95th percentile on an RTX 4060 Ti, with zero
mesh uploads during 90 camera rotations. Larger boards will have different timings.

Windows startup registers a dedicated application identity and loads a
multi-resolution `.ico` for both the application and window. Restart the app after
updating to apply the taskbar identity. `scripts/build_icon.py` regenerates the
icon from the SVG source.

Core libraries: [Gerbonara](https://gerbolyze.gitlab.io/gerbonara/),
[CadQuery](https://cadquery.readthedocs.io/en/stable/), PyQt6, QtAwesome, Shapely
and NumPy, plus PyQtGraph/PyOpenGL for the GPU preview. The layered PCB logo is an
editable SVG in `gerberstep/assets/`.

## Windows and Linux executable builds

Build on the target OS; PyInstaller does not cross-compile Windows/Linux binaries.
Use a 64-bit Python 3.12 environment on either platform:

```text
python -m pip install -r requirements.txt
python -m pip install -e ".[build,test]"
python scripts/build.py
```

Outputs:

| Host | Executable | Portable archive |
| --- | --- | --- |
| Windows | `dist/windows/GerberSTEP.exe` | `dist/GerberSTEP-windows.zip` |
| Linux | `dist/linux/GerberSTEP` | `dist/GerberSTEP-linux.tar.gz` |

Distribute just the executable, or its archive. Python, Qt, CAD libraries, icons
and the demo set are embedded; no Python installation or `_internal` folder is
needed. The executable extracts its bundled dependencies to a temporary directory
at startup, so launching can take longer than a folder build and requires free
temporary disk space.
Builds are unsigned. Linux requires working system OpenGL/EGL libraries and a Qt
desktop platform; Ubuntu CI installs these dependencies in `.github/workflows/build.yml`.
The Linux build targets Ubuntu 24.04 or a compatible/newer glibc environment.

Run the **Build desktop executables** GitHub Actions workflow manually (or push a
`v*` tag) to build both platforms. Each job runs tests and a packaged STEP export
smoke test before uploading its archive. Linux archives preserve executable permissions.
No workflow is dispatched automatically by the local build script.

The bundled diagnostic command `GerberSTEP --self-test report.json` tests icons,
Qt imports, Gerber parsing and a STEP round trip, writing a JSON report. Use
`QT_QPA_PLATFORM=offscreen` for a headless check. It does not test GPU rendering.
