import math

import cadquery as cq
import pytest
from shapely.geometry import Point, box
from shapely.ops import unary_union

from gerberstep.export import build_assembly, export_step, material_solids
from gerberstep.model import Board, DrillHole, Layer, Settings, stack_components


def board_fixture():
    holes = [DrillHole(2, 2, 0.4, True), DrillHole(8, 2, 0.4, False),
             DrillHole(8, 8, 0.4, None)]
    cutouts = unary_union([Point(h.x, h.y).buffer(h.radius, quad_segs=64) for h in holes])
    outline = box(0, 0, 10, 10).difference(cutouts)
    foil = box(1, 1, 3, 3).union(box(7, 1, 9, 3)).difference(cutouts)
    return Board("EMS", outline,
                 [Layer("Top_Copper", "copper", "top", foil),
                  Layer("Bottom_Copper", "copper", "bottom", foil)],
                 drill_holes=holes)


def test_ems_separate_bodies_exact_barrel_and_nonoverlapping_materials(tmp_path):
    board = board_fixture()
    parts = stack_components(board, Settings(ems=True, plating=0.025))
    assert all(p.separate_bodies for p in parts if p.kind == "copper")
    assert len([p for p in parts if p.kind == "copper"]) == 3
    connected = next(p for p in parts if len(p.members) == 3)
    assert {m.name.split("_Body")[0] for m in connected.members} == {"Top_Copper", "Bottom_Copper", "Via_Barrel_0001"}
    assembly = build_assembly(parts)
    assert "Manufacturing_Monolith" not in assembly.objects
    shapes = [child.obj for child in assembly.children]
    assert all(s.isValid() and len(s.Solids()) == 1 for s in shapes)
    via = material_solids(next(m for m in connected.members if m.name.startswith("Via_")))[0]
    conductor = assembly.objects[connected.name].obj
    assert conductor.isInside(cq.Vector(2.7, 2, 1.65))
    assert conductor.isInside(cq.Vector(2.7, 2, -0.05))
    assert conductor.isInside(cq.Vector(2.41, 2, 0.8))
    assert via.Volume() == pytest.approx(math.pi * (0.425**2 - 0.4**2) * 1.8, rel=1e-5)
    assert not via.isInside(cq.Vector(2, 2, 0.8))
    for child in assembly.children:
        if child.name != connected.name:
            assert child.obj.intersect(via).Volume() < 1e-8
    path = tmp_path / "ems.step"
    export_step(parts, path)
    restored = cq.importers.importStep(str(path)).val()
    assert restored.isValid()
    assert len(restored.Solids()) == len(shapes)


def test_ems_visibility_preserves_barrel_height_and_validates_plating():
    board = board_fixture()
    parts = stack_components(board, Settings(ems=True, enabled={"dielectric": False, "Top_Copper": False}))
    via = next(m for p in parts for m in p.members if m.name.startswith("Via_"))
    assert via.z == -0.1
    assert via.thickness == pytest.approx(1.8)
    assert not any(p.kind == "dielectric" for p in parts)
    for thickness in (0, -1, math.nan, math.inf):
        with pytest.raises(ValueError, match="plating"):
            stack_components(board, Settings(ems=True, plating=thickness))


def test_standard_mode_keeps_layer_components():
    parts = stack_components(board_fixture(), Settings())
    assert [p.name for p in parts] == ["Dielectric_1", "Top_Copper", "Bottom_Copper"]
    assert not any(p.separate_bodies for p in parts)


def test_multilayer_via_chain_and_clearance_isolation():
    holes = [DrillHole(2, 2, 0.4, True), DrillHole(8, 2, 0.4, True)]
    cutouts = unary_union([Point(h.x, h.y).buffer(h.radius, quad_segs=64) for h in holes])
    outline = box(0, 0, 10, 10).difference(cutouts)
    layers = [Layer("Top", "copper", "top", box(1, 1, 3, 3).difference(cutouts)),
              Layer("Bridge", "copper", "inner1", box(1, 1, 9, 3).difference(cutouts)),
              Layer("Bottom", "copper", "bottom", box(7, 1, 9, 3).difference(cutouts))]
    board = Board("chain", outline, layers, drill_holes=holes)
    copper = [p for p in stack_components(board, Settings(ems=True)) if p.kind == "copper"]
    assert len(copper) == 1
    assert len(copper[0].members) == 5
    assert len(material_solids(copper[0])) == 1
    # An internal clearance around the second via breaks the chain.
    layers[1].geometry = layers[1].geometry.difference(Point(8, 2).buffer(0.6))
    copper = [p for p in stack_components(board, Settings(ems=True)) if p.kind == "copper"]
    assert len(copper) == 2
    assert sorted(len(p.members) for p in copper) == [2, 3]
    assert all(len(material_solids(p)) == 1 for p in copper)


def test_internal_foil_gaps_contain_dielectric():
    board = board_fixture()
    board.layers.append(Layer("Inner1_Copper", "copper", "inner1", box(4, 4, 6, 6)))
    parts = stack_components(board, Settings(ems=True))
    dielectric = [p for p in parts if p.kind == "dielectric"]
    assert len(dielectric) == 1
    assert dielectric[0].name == "Dielectric"
    filler = [p for p in dielectric[0].members if p.name.startswith("Inner1_Copper_Dielectric")]
    assert filler
    assert all(p.kind == "dielectric" for p in filler)
    assert sum(p.geometry.area for p in filler) == pytest.approx(
        board.outline.area - 4 - math.pi * (0.425**2 - 0.4**2), abs=0.002)
    assert filler[0].z == pytest.approx(0.8)
    assert filler[0].thickness == pytest.approx(0.1)
    assembly = build_assembly(parts)
    substrate = assembly.objects["Dielectric"].obj
    assert substrate.isValid()
    assert len(substrate.Solids()) == 1
    assert substrate.isInside(cq.Vector(5, 3, 0.85))
    assert not substrate.isInside(cq.Vector(5, 5, 0.85))
    assert substrate.isInside(cq.Vector(5, 5, 0.4))
    assert substrate.isInside(cq.Vector(5, 5, 1.2))
    for child in assembly.children:
        if child.name != "Dielectric":
            assert substrate.intersect(child.obj).Volume() < 1e-8


def test_import_preserves_explicit_drill_plating(tmp_path):
    from pathlib import Path
    import shutil
    from gerberstep.geometry import load_board

    demo = Path(__file__).resolve().parents[1] / "examples" / "demo"
    for source in demo.iterdir():
        shutil.copy(source, tmp_path / source.name)
    drill = tmp_path / "demo.drl"
    drill.write_text(drill.read_text().replace("M48", "M48\n;TYPE=PLATED"))
    board = load_board(str(tmp_path))
    assert board.drill_holes
    assert all(h.plated is True for h in board.drill_holes)
