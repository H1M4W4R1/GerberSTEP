"""Render the real Qt window with the demo fixture for visual QA."""
import os
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QFontDatabase
from gerberstep.app import MainWindow, STYLE
from gerberstep.geometry import load_board
from gerberstep.preview import mesh_template

root = Path(__file__).resolve().parents[1]
app = QApplication([])
# The offscreen Windows backend does not discover system fonts on its own.
for font in ["arial.ttf", "arialbd.ttf"]:
    path = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / font
    if path.exists():
        QFontDatabase.addApplicationFont(str(path))
app.setStyle("Fusion")
app.setStyleSheet(STYLE)
window = MainWindow()
window.show()
board = load_board(str(root / "examples" / "demo"), tolerance=window.precision_value)
cache = {id(board.outline): mesh_template(board.outline)}
cache.update({id(layer.geometry): mesh_template(layer.geometry) for layer in board.layers})
window.board_loaded((board, cache))
window.export_button.setEnabled(True)
app.processEvents()
app.processEvents()
out = root / "output"
out.mkdir(exist_ok=True)
window.grab().save(str(out / "preview-3d.png"))
window.view_mode.setCurrentText("2D")
app.processEvents()
window.grab().save(str(out / "preview-2d.png"))
window.view_mode.setCurrentText("3D")
window.explode.setChecked(True)
app.processEvents()
window.grab().save(str(out / "preview-exploded.png"))
window.close()
