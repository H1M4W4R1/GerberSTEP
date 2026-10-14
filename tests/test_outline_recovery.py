"""Malformed fabrication contours must recover without guessing large gaps."""
from types import SimpleNamespace
from shutil import copytree

import pytest
from gerbonara import graphic_primitives as gp
from shapely.geometry import Point

from gerberstep.geometry import board_outline, load_board
from test_conversion import DEMO


def outline(*paths, width=0):
    primitives = [gp.Line(*a, *b, width) for path in paths for a, b in zip(path, path[1:])]
    return SimpleNamespace(objects=[SimpleNamespace(to_primitives=lambda unit: primitives)])


SQUARE = [(0, 0), (10, 0), (10, 10), (0, 10), (0, 0)]


@pytest.mark.parametrize("tolerance", [0.01, 0.05, 0.1])
def test_small_gap_repaired_independently_of_curve_precision(tolerance):
    with pytest.warns(UserWarning, match="bridged 1"):
        shape = board_outline(outline(SQUARE[:-1] + [(0, 0.04)]), tolerance)
    assert shape.is_valid
    assert shape.area == pytest.approx(100)


def test_stray_lines_preserve_closed_cutouts():
    hole = [(2, 2), (4, 2), (4, 4), (2, 4), (2, 2)]
    with pytest.warns(UserWarning, match="ignored"):
        shape = board_outline(outline(SQUARE, hole, [(10, 10), (12, 12)]))
    assert shape.area == pytest.approx(96)
    assert not shape.covers(Point(3, 3))


def test_large_gap_not_guessed():
    with pytest.raises(ValueError, match="open"):
        board_outline(outline(SQUARE[:-1] + [(0, 0.1)]))


def test_ambiguous_nearby_endpoints_not_joined():
    with pytest.raises(ValueError, match="open"):
        board_outline(outline(SQUARE[:-1] + [(0, 0.04)], [(0.01, 0.02), (2, 2)]))


def test_intersections_and_duplicate_edges():
    shape = board_outline(outline(SQUARE, [(0, 5), (10, 5)], SQUARE))
    assert shape.is_valid
    assert shape.area == pytest.approx(100)


def test_import_surfaces_recovery_in_notes(tmp_path):
    copytree(DEMO, tmp_path, dirs_exist_ok=True)
    path = tmp_path / "demo.gko"
    text = path.read_text()
    path.write_text(text.replace("M02*", "X0Y0D02*\nX90000000Y90000000D01*\nM02*"))
    board = load_board(str(tmp_path))
    assert any("ignored" in note and "cutouts" in note for note in board.warnings)
    assert board.outline.bounds == (0, 0, 60, 40)


def test_repaired_cutout_survives_step_export(tmp_path):
    import cadquery as cq
    from gerberstep.export import export_step
    from gerberstep.model import Component

    hole = [(2, 2), (4, 2), (4, 4), (2, 4), (2, 2.04)]
    with pytest.warns(UserWarning, match="bridged 1"):
        shape = board_outline(outline(SQUARE, hole))
    assert shape.area == pytest.approx(96)
    path = tmp_path / "recovered.step"
    export_step([Component("Core", "dielectric", shape, 0, 1.6)], path, add_monolith=False)
    solid = cq.importers.importStep(str(path)).val()
    assert solid.isValid()
    assert solid.Volume() == pytest.approx(96 * 1.6)
    assert not solid.isInside(cq.Vector(3, 3, 0.8))


def test_easyeda_overlapping_offset_outline_strokes():
    cam = outline([(-95.14966, 16.03425), (-95.16493, 41.79491)],
                  [(-95.14966, 41.94225), (-95.14966, 43.21225),
                   (45.94733, 43.21225), (45.94733, -50.76774),
                   (-95.13442, -50.76774), (-95.13442, 30.15157)], width=0.254)
    with pytest.warns(UserWarning, match="overlapping edge strokes"):
        shape = board_outline(cam)
    assert shape.geom_type == "Polygon"
    assert shape.is_valid
    assert len(shape.interiors) == 0
    assert shape.area == pytest.approx(13259.6784036789)
    assert shape.bounds == pytest.approx((-95.16493, -50.76774, 45.94733, 43.21225))


def test_stroke_repair_cannot_exceed_aperture_width_or_half_mm():
    for width, gap in [(0.1, 0.15), (2, 0.6)]:
        with pytest.raises(ValueError, match="open"):
            board_outline(outline(SQUARE[:-1] + [(0, gap)], width=width))


def test_easyeda_inner_layer_names(tmp_path):
    copytree(DEMO, tmp_path, dirs_exist_ok=True)
    (tmp_path / "Gerber_InnerLayer1.G1").write_text((DEMO / "demo.gtl").read_text())
    board = load_board(str(tmp_path))
    assert any(layer.side == "inner1" and layer.kind == "copper" for layer in board.layers)
