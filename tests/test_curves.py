import math
from dataclasses import replace
from pathlib import Path

import cadquery as cq
import pytest
from gerbonara import graphic_primitives as gp
from shapely.geometry import Point, Polygon, box

from gerberstep.export import build_assembly, component_solids, export_step
from gerberstep.geometry import load_board, primitive_geometry
from gerberstep.model import Component, DrillHole, Settings, stack_components


def test_round_pad_and_trace_caps_have_exact_volume_and_circular_edges(tmp_path):
    pad = Component("Pad", "copper", primitive_geometry(gp.Circle(0, 0, 2), 0.05), 0, 0.1,
                    circles=((0, 0, 2),), tolerance=0.05)
    trace = Component("Trace", "copper", primitive_geometry(gp.Line(0, 0, 10, 0, 2), 0.05),
                      0, 0.1, circles=((0, 0, 1), (10, 0, 1)), tolerance=0.05)
    for part, area, faces in ((pad, 4*math.pi, 3), (trace, 20+math.pi, 6)):
        path = tmp_path / f"{part.name}.step"
        export_step([part], path)
        solid = cq.importers.importStep(str(path)).val()
        assert solid.isValid()
        assert solid.Volume() == pytest.approx(area*0.1)
        assert len(solid.Faces()) == faces
        assert any(edge.geomType() == "CIRCLE" for edge in solid.Edges())


def test_round_pad_with_exact_drill_keeps_annular_copper(tmp_path):
    geometry = primitive_geometry(gp.Circle(0, 0, 2), 0.05).difference(
        primitive_geometry(gp.Circle(0, 0, 0.6), 0.05))
    part = Component("Pad", "copper", geometry, 0, 0.1,
                     [DrillHole(0, 0, 0.6)], ((0, 0, 2),), 0.05)
    path = tmp_path / "pad.step"
    export_step([part], path)
    solid = cq.importers.importStep(str(path)).val()
    assert solid.isValid()
    assert solid.Volume() == pytest.approx(math.pi*(4-0.36)*0.1)
    assert len(solid.Faces()) == 4
    assert not solid.isInside(cq.Vector(0, 0, 0.05))
    assert solid.isInside(cq.Vector(1, 0, 0.05))


def test_polygon_pad_is_not_guessed_to_be_a_circle():
    hexagon = Polygon([(math.cos(i*math.pi/3), math.sin(i*math.pi/3)) for i in range(6)])
    part = Component("Hex", "copper", hexagon, 0, 0.1, circles=((20, 20, 1),))
    solid, = component_solids(part)
    assert solid.Volume() == pytest.approx(hexagon.area*0.1)
    assert all(face.geomType() == "PLANE" for face in solid.Faces())


def test_clipped_circle_keeps_cut_boundary():
    geometry = primitive_geometry(gp.Circle(0, 0, 2), 0.05).intersection(box(-1, -3, 3, 3))
    part = Component("Clipped", "copper", geometry, 0, 0.1, circles=((0, 0, 2),), tolerance=0.05)
    solid, = component_solids(part)
    assert solid.isValid()
    assert solid.BoundingBox().xmin == pytest.approx(-1)
    assert not solid.isInside(cq.Vector(-1.1, 0, 0.05))
    assert solid.isInside(cq.Vector(1.9, 0, 0.05))
    assert any(face.geomType() == "CYLINDER" for face in solid.Faces())


@pytest.mark.parametrize("holes", [False, True])
def test_recovery_does_not_merge_islands_or_overlapping_holes(holes):
    # The inscribed octagons are separate, but their source circles overlap.
    x, y = 1.99*math.cos(math.pi/8), 1.99*math.sin(math.pi/8)
    a, b = Point(0, 0).buffer(1, quad_segs=2), Point(x, y).buffer(1, quad_segs=2)
    assert a.disjoint(b)
    geometry = box(-5, -5, 5, 5).difference(a.union(b)) if holes else a.union(b)
    part = Component("Narrow", "copper", geometry, 0, 0.1,
                     circles=((0, 0, 1), (x, y, 1)), tolerance=0.1)
    solids = component_solids(part)
    assert len(solids) == (1 if holes else 2)
    assert all(s.isValid() for s in solids)
    assert sum(s.Volume() for s in solids) == pytest.approx(geometry.area*0.1)
    assert all(f.geomType() == "PLANE" for s in solids for f in s.Faces())


def test_demo_monolith_has_fewer_faces_with_same_precision():
    demo = Path(__file__).resolve().parents[1] / "examples" / "demo"
    board = load_board(str(demo), tolerance=0.05)
    parts = stack_components(board, Settings())
    original = build_assembly([replace(p, circles=()) for p in parts]).objects["Manufacturing_Monolith"].obj
    recovered = build_assembly(parts).objects["Manufacturing_Monolith"].obj
    assert recovered.isValid()
    assert len(recovered.Solids()) == 1
    assert len(recovered.Faces()) < len(original.Faces())*0.7
    assert recovered.BoundingBox().xlen == pytest.approx(original.BoundingBox().xlen)
    assert recovered.BoundingBox().ylen == pytest.approx(original.BoundingBox().ylen)
    assert recovered.BoundingBox().zlen == pytest.approx(original.BoundingBox().zlen)
