from pathlib import Path

import cadquery as cq
import pytest
from gerbonara import graphic_primitives as gp
from shapely.geometry import Point, box

from gerberstep.export import build_assembly, export_step
from gerberstep.geometry import load_board, polygons, primitive_geometry
from gerberstep.model import Component, Settings, stack_components

DEMO = Path(__file__).resolve().parents[1] / "examples" / "demo"


def test_precision_reduces_faces_within_chord_tolerance():
    counts = []
    for tolerance in (0.01, 0.05, 0.1):
        shape = primitive_geometry(gp.Circle(0, 0, 1.5), tolerance)
        coordinates = list(shape.exterior.coords)
        counts.append(len(coordinates))
        for a, b in zip(coordinates, coordinates[1:]):
            midpoint = Point((a[0]+b[0])/2, (a[1]+b[1])/2)
            assert 1.5-midpoint.distance(Point(0, 0)) <= tolerance+1e-10
    assert counts[0] > counts[1] > counts[2]
    boards = [load_board(str(DEMO), tolerance=t) for t in (0.01, 0.1)]
    counts = [sum(len(p.exterior.coords)+sum(len(r.coords) for r in p.interiors)
                  for layer in board.layers for p in polygons(layer.geometry)) for board in boards]
    assert counts[1] < counts[0]*0.6
    assert boards[1].tolerance == 0.1
    assert boards[1].source_path == str(DEMO.resolve())


def test_monolith_is_one_solid_preserves_hole_and_trace_relief(tmp_path):
    substrate = box(0, 0, 10, 10).difference(box(4, 4, 6, 6))
    copper = box(1, 1, 3, 3).union(box(7, 7, 9, 9))
    parts = [Component("Core", "dielectric", substrate, 0, 1.6),
             Component("Top_Copper", "copper", copper, 1.6, 0.1),
             Component("Silk", "silk", box(1, 5, 2, 6), 1.7, 0.1)]
    assembly = build_assembly(parts)
    assert len(assembly.children) == 4
    solid = assembly.objects["Manufacturing_Monolith"].obj
    assert solid.isValid()
    assert len(solid.Solids()) == 1
    assert solid.Volume() == pytest.approx(96*1.6+8*0.1)
    assert not solid.isInside(cq.Vector(5, 5, 0.8))  # through hole retained
    assert solid.isInside(cq.Vector(2, 2, 1.65))  # trace retained
    assert not solid.isInside(cq.Vector(5, 2, 1.65))  # gaps are not filled
    assert not solid.isInside(cq.Vector(1.5, 5.5, 1.75))  # silk excluded
    file = tmp_path / "manufacturing.step"
    export_step(parts, file)
    result = cq.importers.importStep(str(file)).val()
    assert result.isValid()
    assert "Manufacturing_Monolith" in file.read_text()
    assert len(result.Solids()) == 5  # core, two copper islands, silk, and one monolith


def test_monolith_handles_internal_copper_and_rejects_disconnected_boards():
    substrate = box(0, 0, 10, 10)
    parts = [Component("Core1", "dielectric", substrate, 0, 0.8),
             Component("Inner", "copper", box(1, 1, 2, 2), 0.8, 0.1),
             Component("Core2", "dielectric", substrate, 0.9, 0.8)]
    monolith = build_assembly(parts).objects["Manufacturing_Monolith"].obj
    assert len(monolith.Solids()) == 1
    detached = [Component("Panel", "dielectric", box(0, 0, 2, 2).union(box(4, 0, 6, 2)), 0, 1.6)]
    with pytest.raises(ValueError, match="one connected solid"):
        build_assembly(detached)
    assert len(build_assembly(detached, add_monolith=False).children) == 1
