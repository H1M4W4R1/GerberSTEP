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


def test_async_import_controls_and_preview(app):
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
    window.copper.setValue(0.05)
    assert all(p.thickness == 0.05 for p in window.components if p.kind == "copper")
    window.optional["Top_Silkscreen"][0].setChecked(False)
    assert len(window.components) == 6
    window.coplanar.click()
    top_mask = next(p for p in window.components if p.name == "Top_Soldermask")
    assert top_mask.z == 1.6
    window.view_mode.setCurrentText("2D")
    window.side.setCurrentText("Bottom")
    assert window.preview.bottom
    assert not window.grab().isNull()
    window.view_mode.setCurrentText("3D")
    assert not window.grab().isNull()
    window.close()
