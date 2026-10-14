"""Scene lifetime checks; these do not need a live OpenGL context."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PyQt6.QtWidgets import QApplication
from shapely.geometry import box

from gerberstep.app import application_icon
from gerberstep.gpu_preview import GPUPreview
from gerberstep.model import Component
from gerberstep.preview import mesh_template


def test_mesh_survives_camera_thickness_and_explode_changes():
    app = QApplication.instance() or QApplication([])
    view = GPUPreview()
    geometry = box(0, 0, 10, 10)
    templates = {id(geometry): mesh_template(geometry)}
    part = Component("copper", "copper", geometry, 1.6, 0.1)
    view.set_scene([part], templates, np.array([5, 5, 0]), 10, False)
    item = view.mesh_items["copper"][1]
    mesh = item.opts["meshdata"]
    assert mesh.faceColors(indexed="faces").shape == (len(templates[id(geometry)]), 3, 4)
    for _ in range(30):
        view.orbit(2, 1)
    part.thickness = 0.075
    part.z = 2
    view.set_scene([part], templates, np.array([5, 5, 0]), 10, True)
    assert view.mesh_builds == 1
    assert view.mesh_items["copper"][1] is item
    assert item.opts["meshdata"] is mesh
    old_colors = mesh.faceColors(indexed="faces").copy()
    part.color_override = "#123456"
    view.set_scene([part], templates, np.array([5, 5, 0]), 10, True)
    assert view.mesh_builds == 1
    assert view.mesh_items["copper"][1] is item
    assert not np.array_equal(old_colors, mesh.faceColors(indexed="faces"))
    assert abs(item.transform().map(np.array([0., 0., 1.]))[2] - 2.075) < 1e-5
    view.set_scene([], templates, np.zeros(3), 10, False)
    assert not view.mesh_items
    assert not view.items
    view.close()


def test_windows_icon_has_taskbar_and_high_dpi_sizes():
    app = QApplication.instance() or QApplication([])
    icon = application_icon()
    assert not icon.isNull()
    assert {16, 32, 48, 256}.issubset({size.width() for size in icon.availableSizes()})
    assert not icon.pixmap(32, 32).isNull()


def test_ems_generated_bodies_render_in_software_and_gpu_scene():
    from shapely.geometry import Point
    from gerberstep.model import Board, DrillHole, Layer, Settings, stack_components
    from gerberstep.preview import BoardPreview

    app = QApplication.instance() or QApplication([])
    geometry = box(0, 0, 10, 10).difference(Point(5, 5).buffer(0.5))
    board = Board("EMS", geometry,
                  [Layer("Top_Copper", "copper", "top", geometry)],
                  drill_holes=[DrillHole(5, 5, 0.5, True)])
    view = BoardPreview()
    view.resize(420, 340)
    view.set_components(stack_components(board, Settings()))
    parts = stack_components(board, Settings(ems=True))
    view.set_components(parts)
    assert any(m.name.startswith("Via_Barrel") for p in parts for m in p.members)
    assert set(view.cache) == {id(p.geometry) for p in parts}
    assert all(len(view.cache[id(p.geometry)]) > 0 for p in parts)
    rendered = view.grab().toImage()
    # Copper is red-dominant; background, grid and labels are blue-dominant.
    copper_pixels = sum(rendered.pixelColor(x, y).red() > rendered.pixelColor(x, y).blue() * 1.3
                        for y in range(40, 290, 3) for x in range(40, 380, 3))
    assert copper_pixels > 100
    gpu = GPUPreview()
    gpu.set_scene(parts, view.cache, view.center, view.span, False)
    assert set(gpu.mesh_items) == {p.name for p in parts}
    updated = stack_components(board, Settings(ems=True, plating=0.04))
    view.set_components(updated)
    gpu.set_scene(updated, view.cache, view.center, view.span, False)
    assert set(view.cache) == {id(p.geometry) for p in updated}
    view.set_components(stack_components(board, Settings()))
    gpu.set_scene(view.parts, view.cache, view.center, view.span, False)
    assert set(gpu.mesh_items) == {p.name for p in view.parts}
    gpu.close()
    view.close()
