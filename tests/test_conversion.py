from pathlib import Path
from zipfile import ZipFile

import pytest
from gerbonara import GerberFile
from gerbonara import graphic_primitives as gp
from shapely.geometry import Point, box

from gerberstep.export import build_assembly, export_step
from gerberstep.geometry import board_outline, layer_geometry, load_board, primitive_geometry
from gerberstep.model import Board, Layer, Settings, stack_components

DEMO = Path(__file__).resolve().parents[1] / "examples" / "demo"


def test_demo_loads_mask_openings_and_drills():
    board = load_board(str(DEMO))
    assert board.outline.bounds == (0, 0, 60, 40)
    assert len(board.layers) == 6
    assert not board.outline.covers(Point(3, 3))
    mask = next(layer.geometry for layer in board.layers if layer.kind == "mask" and layer.side == "top")
    assert not mask.covers(Point(25, 13))
    assert mask.covers(Point(30, 20))
    assert len(stack_components(board, Settings())) == 7


def test_zip_and_selected_file(tmp_path):
    path = tmp_path / "board.zip"
    with ZipFile(path, "w") as archive:
        for file in DEMO.iterdir():
            archive.write(file, f"fabrication/{file.name}")
    loaded = load_board(str(path))
    assert len(loaded.layers) == 6
    assert loaded.name == "board"
    assert len(load_board(str(DEMO / "demo.gtl")).layers) == 6


def test_heights_and_coplanar_mode():
    board = load_board(str(DEMO))
    parts = {p.name: p for p in stack_components(board, Settings())}
    assert parts["Top_Copper"].z == 1.6
    assert parts["Top_Soldermask"].z == pytest.approx(1.7)
    assert parts["Top_Silkscreen"].z == pytest.approx(1.8)
    assert parts["Bottom_Silkscreen"].z == pytest.approx(-0.3)
    config = Settings(coplanar=True, enabled={"Top_Silkscreen": False}, thicknesses={"Bottom_Silkscreen": 0.075})
    parts = {p.name: p for p in stack_components(board, config)}
    assert "Top_Silkscreen" not in parts
    assert parts["Top_Soldermask"].z == parts["Top_Copper"].z
    assert parts["Bottom_Silkscreen"].z == -0.075
    assert parts["Bottom_Silkscreen"].z + parts["Bottom_Silkscreen"].thickness == 0


def test_inner_stack_order_and_dielectric_total():
    outline = box(0, 0, 10, 10)
    board = Board("four", outline, [Layer(side, "copper", side, outline)
                                   for side in ("top", "inner1", "inner2", "bottom")])
    parts = stack_components(board, Settings())
    assert sum(p.thickness for p in parts if p.kind == "dielectric") == pytest.approx(1.6)
    by_name = {p.name: p for p in parts}
    assert by_name["inner1"].z > by_name["inner2"].z
    assert by_name["top"].z == pytest.approx(1.8)
    assert len(parts) == 7


def gerber(body, apertures="%ADD10C,0.1*%"):
    return GerberFile.from_string("%FSLAX46Y46*%\n%MOMM*%\n" + apertures + "\nD10*\nG01*\n" + body + "\nM02*")


def test_clear_polarity_and_aperture_hole_composition():
    cam = gerber("X0Y0D03*\nD11*\nX0Y0D03*", "%ADD10C,1*%\n%ADD11C,3X2*%")
    shape = layer_geometry(cam)
    assert shape.covers(Point(0, 0))  # annular aperture must not erase previous pad
    assert not shape.covers(Point(0.8, 0))
    clear = gerber("X0Y0D03*\n%LPC*%\nD11*\nX0Y0D03*", "%ADD10C,3*%\n%ADD11C,1*%")
    assert not layer_geometry(clear).covers(Point(0, 0))


def test_outline_cutout_and_open_contour():
    cam = gerber("X0Y0D02*\nX10000000Y0D01*\nX10000000Y10000000D01*\nX0Y10000000D01*\nX0Y0D01*\n"
                 "X2000000Y2000000D02*\nX4000000Y2000000D01*\nX4000000Y4000000D01*\nX2000000Y4000000D01*\nX2000000Y2000000D01*")
    assert board_outline(cam).area == pytest.approx(96)
    with pytest.raises(ValueError, match="open"):
        board_outline(gerber("X0Y0D02*\nX10000000Y0D01*"))


def test_rotated_rectangle_and_arc():
    import math
    assert primitive_geometry(gp.Rectangle(0, 0, 4, 2, math.pi/4)).area == pytest.approx(8)
    arc = primitive_geometry(gp.Arc(5, 0, -5, 0, 0, 0, False, 1))
    assert arc.area == pytest.approx(math.pi*5 + math.pi/4, abs=0.25)


def test_full_circle_arc_and_inch_units():
    import math
    ring = primitive_geometry(gp.Arc(5, 0, 5, 0, 0, 0, False, 1))
    assert ring.area == pytest.approx(10*math.pi, abs=0.2)
    assert not ring.covers(Point(0, 0))
    cam = GerberFile.from_string("%FSLAX24Y24*%\n%MOIN*%\n%ADD10C,0.1*%\nD10*\nX10000Y10000D03*\nM02*")
    assert layer_geometry(cam).centroid.x == pytest.approx(25.4)
    assert layer_geometry(cam).bounds[2] == pytest.approx(26.67)


def test_missing_outline_is_rejected(tmp_path):
    (tmp_path / "board.gtl").write_text((DEMO / "demo.gtl").read_text())
    with pytest.raises(ValueError, match="outline"):
        load_board(str(tmp_path))


def test_depth_buffer_uses_pixel_depth():
    import numpy as np
    from gerberstep.preview import rasterize
    triangles = np.array([[[0, 0, 0], [8, 0, 8], [0, 8, 0]],
                          [[0, 0, 4], [8, 0, 4], [0, 8, 4]]], dtype=float)
    image = rasterize(triangles, [[255, 0, 0], [0, 255, 0]], 10, 10)
    assert list(image[1, 1, :3]) == [0, 255, 0]
    assert list(image[1, 6, :3]) == [255, 0, 0]


def test_step_roundtrip_has_separate_valid_solids(tmp_path):
    import cadquery as cq
    board = load_board(str(DEMO))
    parts = stack_components(board, Settings())
    assembly = build_assembly(parts, add_monolith=False)
    assert len(assembly.children) == 7
    path = tmp_path / "demo.step"
    export_step(parts, path, add_monolith=False)
    text = path.read_text()
    for part in parts:
        assert part.name in text
    result = cq.importers.importStep(str(path)).val()
    assert result.isValid()
    bounds = result.BoundingBox()
    assert bounds.xlen == pytest.approx(60)
    assert bounds.ylen == pytest.approx(40)
    assert bounds.zlen == pytest.approx(2.2)
    # Export replaces the inscribed preview holes with exact cylinders.
    from shapely.ops import unary_union
    holes = unary_union([Point(h.x, h.y).buffer(h.radius, quad_segs=1024)
                         for h in board.drill_holes])
    expected = sum(p.geometry.difference(holes).area*p.thickness for p in parts)
    # Source arcs recover the true curves within the preview's chord tolerance.
    allowed = sum(p.geometry.length * board.tolerance * p.thickness for p in parts)
    assert sum(s.Volume() for s in result.Solids()) == pytest.approx(expected, abs=allowed)
