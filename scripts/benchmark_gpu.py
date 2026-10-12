"""Exercise the real Windows OpenGL viewport and report steady-state latency."""
import json
import statistics
import time
from pathlib import Path

from PyQt6.QtWidgets import QApplication
from OpenGL.GL import glFinish, glGetString, GL_RENDERER
from gerberstep.app import MainWindow, STYLE, application_icon, configure_windows_identity
from gerberstep.geometry import load_board
from gerberstep.preview import mesh_template

root = Path(__file__).resolve().parents[1]
configure_windows_identity()
app = QApplication([])
app.setWindowIcon(application_icon())
app.setStyleSheet(STYLE)
window = MainWindow()
board = load_board(str(root / "examples/demo"), tolerance=window.precision.currentData())
templates = {id(board.outline): mesh_template(board.outline)}
templates.update({id(layer.geometry): mesh_template(layer.geometry) for layer in board.layers})
window.board_loaded((board, templates))
window.show()
for _ in range(10):
    app.processEvents()
gpu = window.preview.gpu
assert gpu is not None and gpu.isValid(), "Native OpenGL context failed"
gpu.makeCurrent()
renderer = glGetString(GL_RENDERER).decode()
gpu.doneCurrent()
uploads = []
for _, item in gpu.mesh_items.values():
    original = item.upload_vertex_buffers
    def tracked(dirty, original=original):
        uploads.append(1)
        return original(dirty)
    item.upload_vertex_buffers = tracked
builds = gpu.mesh_builds
elapsed = []
for _ in range(90):
    start = time.perf_counter()
    gpu.orbit(2, 0.2)
    gpu.repaint()
    app.processEvents()
    gpu.makeCurrent()
    glFinish()
    gpu.doneCurrent()
    elapsed.append((time.perf_counter()-start)*1000)
assert gpu.mesh_builds == builds
assert not uploads, "Camera movement re-uploaded mesh buffers"
gpu.fit()
app.processEvents()
out = root / "output"
out.mkdir(exist_ok=True)
window.grab().save(str(out / "preview-gpu.png"))
report = {"renderer": renderer, "frames": len(elapsed), "mesh_builds": builds,
          "camera_mesh_uploads": len(uploads), "median_ms": round(statistics.median(elapsed), 2),
          "p95_ms": round(sorted(elapsed)[int(len(elapsed)*0.95)], 2)}
(out / "gpu-benchmark.json").write_text(json.dumps(report, indent=2))
print(json.dumps(report))
window.close()
