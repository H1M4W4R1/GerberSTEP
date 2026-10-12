"""Bundled-app smoke test; exercises resources, parser, Qt and STEP export."""
import json
import tempfile
import traceback
from pathlib import Path


def run(report_path):
    report = Path(report_path).resolve()
    report.parent.mkdir(parents=True, exist_ok=True)
    try:
        import cadquery as cq
        from PyQt6.QtWidgets import QApplication
        from .app import MainWindow, application_icon
        from .gpu_preview import GPUPreview
        from .geometry import load_board
        from .model import Settings, stack_components
        from .export import export_step
        app = QApplication.instance() or QApplication([])
        assert not application_icon().isNull()
        window = MainWindow()
        board = load_board(str(Path(__file__).resolve().parents[1] / "examples" / "demo"), tolerance=0.1)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "demo.step"
            export_step(stack_components(board, Settings()), path)
            solid = cq.importers.importStep(str(path)).val()
            assert solid.isValid()
        window.close()
        result = {"ok": True, "layers": len(board.layers), "icon": True, "step_roundtrip": True}
    except Exception:
        result = {"ok": False, "error": traceback.format_exc()}
    report.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return 0 if result["ok"] else 1
