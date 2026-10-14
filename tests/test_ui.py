import os
import time
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"

import pytest
from PyQt6.QtWidgets import QApplication
from gerberstep.app import MainWindow, STYLE


@pytest.fixture(scope="module")
def app():
    app = QApplication.instance() or QApplication([])
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    return app


def test_async_import_controls_and_preview(app, monkeypatch):
    window = MainWindow()
    errors = []
    window.show_error = lambda message, details: errors.append(message)
    window.show()
    window.open_path(str(Path(__file__).resolve().parents[1] / "examples" / "demo"))
    deadline = time.monotonic()+30
    while window.task is not None and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    assert not errors
    assert window.task is None
    assert window.export_button.isEnabled()
    assert len(window.components) == 7
    assert window.monolith_available()
    assert window.board.tolerance == 0.05
    monkeypatch.setattr("gerberstep.app.QInputDialog.getText", lambda *args, **kwargs: ("My export.step", True))
    window.rename_button.click()
    assert window.board.name == "My export"
    assert window.board_title.text() == "My export"
    for name in ("Top_Copper", "Bottom_Copper"):
        window.optional[name][1].setValue(0.05)
    assert all(p.thickness == 0.05 for p in window.components if p.kind == "copper")
    window.optional["Top_Silkscreen"][0].setChecked(False)
    assert len(window.components) == 6
    window.coplanar.click()
    top_mask = next(p for p in window.components if p.name == "Top_Soldermask")
    assert top_mask.z == pytest.approx(1.65)
    assert next(p for p in window.export_components if p.name == "Top_Soldermask").z == 1.6
    window.optional["Bottom_Soldermask"][1].setValue(0.075)
    window.precision_menu.actions()[0].trigger()
    deadline = time.monotonic()+30
    while window.task is not None and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    assert not errors
    assert window.task is None
    assert window.board.tolerance == 0.1
    assert window.board.name == "My export"
    assert window.optional["Top_Copper"][1].value() == 0.05
    assert window.coplanar.isChecked()
    assert not window.optional["Top_Silkscreen"][0].isChecked()
    assert window.optional["Bottom_Soldermask"][1].value() == 0.075
    window.view_mode.setCurrentText("2D")
    window.side.setCurrentText("Bottom")
    assert window.preview.bottom
    assert not window.grab().isNull()
    window.view_mode.setCurrentText("3D")
    assert not window.grab().isNull()
    window.view_mode.setCurrentText("EMS")
    assert window.preview.mode == "3D"
    assert window.settings.ems
    assert window.plating.isEnabled()
    assert not window.coplanar.isEnabled()
    assert not window.monolith_available()
    assert all(p.separate_bodies for p in window.export_components if p.kind == "copper")
    assert len([p for p in window.components if p.kind == "dielectric"]) == 1
    assert all(p.kind in ("copper", "dielectric") for p in window.components)
    window.plating.setValue(0.035)
    assert window.settings.plating == 0.035
    assert not window.grab().isNull()
    window.view_mode.setCurrentText("3D")
    assert window.monolith_available()
    assert window.coplanar.isEnabled()
    for name, check in window.layer_checks.items():
        check.setChecked(name == "Top_Silkscreen")
    assert [p.name for p in window.export_components] == ["Top_Silkscreen"]
    assert window.export_button.isEnabled()
    assert not window.monolith_available()
    assert window.layer_layout.contentsMargins().right() >= 12
    window.layer_checks["Top_Silkscreen"].setChecked(False)
    assert not window.export_components
    assert not window.export_button.isEnabled()
    assert not window.grab().isNull()
    window.close()


def test_individual_dielectric_controls_survive_rebuild(app):
    from shapely.geometry import box
    from gerberstep.model import Board, Layer

    shape = box(0, 0, 10, 10)
    board = Board("Multilayer", shape, [Layer(side, "copper", side, shape)
                                      for side in ("top", "inner1", "inner2", "bottom")])
    window = MainWindow()
    window.board_loaded((board, {}))
    assert sum(p.thickness for p in window.components if p.kind == "dielectric") == pytest.approx(1.6)
    for name, value in [("Dielectric_1", 0.2), ("Dielectric_2", 0.8), ("Dielectric_3", 0.4), ("inner2", 0.035)]:
        window.optional[name][1].setValue(value)
    window.layer_checks["Dielectric_2"].setChecked(False)
    window.board_loaded((board, {}), preserve=True)
    parts = {p.name: p for p in window.export_components}
    assert "Dielectric_2" not in parts
    assert parts["Dielectric_1"].thickness == 0.2
    assert parts["Dielectric_3"].thickness == 0.4
    assert parts["top"].z == pytest.approx(1.535)
    assert window.optional["Dielectric_2"][1].value() == 0.8
    assert not window.optional["Dielectric_2"][1].isEnabled()
    window.close()


def test_stackup_and_appearance_controls(app):
    from tests.test_stackups import board_with_layers
    from gerberstep.model import MASK_COLORS, FINISH_COLORS

    board = board_with_layers(4)
    window = MainWindow()
    window.board_loaded((board, {}))
    from PyQt6.QtCore import QTimer, Qt
    from PyQt6.QtTest import QTest
    window.show()
    app.processEvents()
    for kind, menu in window.appearance_menus.items():
        visible = []
        menu.aboutToShow.connect(lambda: visible.append(True))
        QTimer.singleShot(50, menu.close)
        QTest.mouseClick(window.legend_labels[kind][0], Qt.MouseButton.LeftButton)
        app.processEvents()
        assert visible
    for kind, value in [("mask", "Blue"), ("silk", "Black"), ("copper", "ENIG")]:
        action = next(a for a in window.appearance_menus[kind].actions() if a.text() == value)
        action.trigger()
        assert action.isChecked()
    window.layer_checks["inner1"].setChecked(False)
    window.apply_stackup_button.click()
    assert window.optional["inner1"][1].value() == 0.0152
    assert window.optional["Dielectric_1"][1].value() == 0.2104
    assert not window.layer_checks["inner1"].isChecked()
    assert window.optional["Mask"][1].value() == 0.1
    window.board_loaded((board, {}), preserve=True)
    parts = {p.name: p for p in window.export_components}
    assert parts["Mask"].color == MASK_COLORS["Blue"]
    assert parts["top"].color == FINISH_COLORS["ENIG"]
    assert parts["Dielectric_1"].thickness == 0.2104
    window.board_loaded((board_with_layers(6), {}))
    assert not window.apply_stackup_button.isEnabled()
    window.close()
