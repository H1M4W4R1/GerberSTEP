import pytest
from shapely.geometry import box

from gerberstep.model import Board, Layer, Settings, COLORS, FINISH_COLORS, stack_components
from gerberstep.stackups import STACKUPS
from gerberstep.export import build_assembly


def board_with_layers(count):
    shape = box(0, 0, 10, 10)
    sides = ["top", *(f"inner{i}" for i in range(1, count - 1)), "bottom"]
    return Board("Test", shape, [Layer(side, "copper", side, shape) for side in sides]
                 + [Layer("Mask", "mask", "top", shape), Layer("Silk", "silk", "top", shape)])


def test_published_stackup_positions_and_compatibility():
    board = board_with_layers(4)
    preset = next(p for p in STACKUPS if "7628" in p.name)
    parts = {p.name: p for p in stack_components(board, Settings(thicknesses=preset.thicknesses(board)))}
    assert parts["inner2"].z == pytest.approx(0.2104)
    assert parts["inner1"].z == pytest.approx(0.2104 + 0.0152 + 1.065)
    assert parts["top"].z + parts["top"].thickness - parts["bottom"].z == pytest.approx(1.5862)
    with pytest.raises(ValueError):
        preset.thicknesses(board_with_layers(2))
    assert not any(p.matches(board_with_layers(6)) for p in STACKUPS)


@pytest.mark.parametrize("finish", ["HASL", "ENIG"])
def test_appearance_reaches_step_assembly_without_changing_geometry(finish):
    board = board_with_layers(4)
    parts = stack_components(board, Settings(mask_color="#123456", silk_color="#222222", finish=finish))
    assembly = build_assembly(parts, add_monolith=False)
    expected = {"top": FINISH_COLORS[finish], "bottom": FINISH_COLORS[finish],
                "inner1": COLORS["copper"], "Mask": "#123456", "Silk": "#222222"}
    for name, color in expected.items():
        assert assembly.objects[name].color.toTuple()[:3] == pytest.approx(
            tuple(int(color[i:i+2], 16)/255 for i in (1, 3, 5)), abs=1e-6)
    baseline = stack_components(board, Settings())
    assert [(p.z, p.thickness, p.geometry) for p in parts] == [(p.z, p.thickness, p.geometry) for p in baseline]
