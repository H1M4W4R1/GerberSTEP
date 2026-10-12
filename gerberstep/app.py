import os
import sys
import traceback
from pathlib import Path

os.environ.setdefault("QT_API", "pyqt6")

import qtawesome as qta
from PyQt6.QtCore import QLocale, QThread, Qt, pyqtSignal
from PyQt6.QtGui import QAction, QIcon, QKeySequence
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFrame,
    QHBoxLayout, QLabel, QLayout, QMainWindow, QMessageBox, QProgressBar, QPushButton,
    QScrollArea, QSplitter, QVBoxLayout, QWidget,
)

from .export import export_step
from .geometry import load_board
from .model import COLORS, Settings, stack_components
from .preview import BoardPreview, mesh_template

ASSETS = Path(__file__).parent / "assets"

STYLE = """
QWidget { background: #101927; color: #dce7f8; font-family: 'Inter', 'Arial'; font-size: 13px; }
QMainWindow { background: #101927; }
QLabel { background: transparent; }
QLabel#title { font-size: 23px; font-weight: 700; }
QLabel#subtitle, QLabel#muted { color: #869bb6; }
QLabel#section { color: #8fabc9; font-size: 11px; font-weight: 700; letter-spacing: 2px; }
QLabel#boardTitle { font-size: 19px; font-weight: 600; }
QFrame#card { background: #162235; border: 1px solid #273951; border-radius: 10px; }
QPushButton { background: #1c2b41; border: 1px solid #30455f; border-radius: 6px; padding: 9px 14px; font-weight: 600; }
QPushButton:hover { background: #263e5c; border-color: #4d88c2; }
QPushButton:pressed, QPushButton:checked { background: #153d68; border-color: #3999ff; color: #9dd1ff; }
QPushButton:disabled { color: #53677f; background: #172235; border-color: #253449; }
QPushButton#primary { background: #287dea; color: white; border-color: #489dff; }
QPushButton#primary:hover { background: #3993ff; }
QPushButton#primary:disabled { background: #253e60; color: #7b91b1; border-color: #304765; }
QDoubleSpinBox, QComboBox { background: #0e1725; border: 1px solid #344963; border-radius: 5px; padding: 6px; min-height: 21px; }
QDoubleSpinBox:focus, QComboBox:focus { border-color: #429bff; }
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button { width: 18px; }
QCheckBox { spacing: 8px; background: transparent; }
QCheckBox::indicator { width: 16px; height: 16px; }
QScrollArea { border: none; }
QScrollBar:vertical { background: #111b2b; width: 9px; }
QScrollBar::handle:vertical { background: #354e6b; border-radius: 4px; min-height: 30px; }
QProgressBar { border: none; background: #1c2b40; height: 3px; }
QProgressBar::chunk { background: #3d9dff; }
QToolTip { background: #21334d; color: #e0edff; border: 1px solid #49688e; padding: 6px; }
QStatusBar { color: #8da5c1; background: #0d1521; }
"""


class Task(QThread):
    progress = pyqtSignal(str)
    succeeded = pyqtSignal(object)
    failed = pyqtSignal(str, str)

    def __init__(self, function, parent=None):
        super().__init__(parent)
        self.function = function

    def run(self):
        try:
            self.succeeded.emit(self.function(self.progress.emit))
        except Exception as exc:
            self.failed.emit(str(exc), traceback.format_exc())


def label(text, name=None):
    widget = QLabel(text)
    if name:
        widget.setObjectName(name)
    return widget


def button(text, icon=None, primary=False):
    widget = QPushButton(text)
    if icon:
        widget.setIcon(qta.icon(icon, color="#bddaff"))
    if primary:
        widget.setObjectName("primary")
    return widget


def spin(value):
    widget = QDoubleSpinBox()
    widget.setLocale(QLocale.c())
    widget.setDecimals(3)
    widget.setRange(0.001, 20.0)
    widget.setSingleStep(0.025)
    widget.setSuffix(" mm")
    widget.setValue(value)
    widget.setMinimumWidth(112)
    widget.setKeyboardTracking(False)
    return widget


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.board = None
        self.task = None
        self.settings = Settings()
        self.components = []
        self.optional = {}
        self.setWindowTitle("GerberSTEP · PCB to mechanical assembly")
        self.setWindowIcon(QIcon(str(ASSETS / "logo.svg")))
        self.resize(1320, 860)
        self.setMinimumSize(1040, 700)
        self.setAcceptDrops(True)
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(24, 20, 24, 12)
        layout.setSpacing(18)

        header = QHBoxLayout()
        logo = QLabel()
        logo.setPixmap(self.windowIcon().pixmap(52, 52))
        header.addWidget(logo)
        branding = QVBoxLayout()
        branding.setSpacing(0)
        branding.addWidget(label("GerberSTEP", "title"))
        branding.addWidget(label("FABRICATION FILES  →  MECHANICAL ASSEMBLY", "subtitle"))
        header.addLayout(branding)
        header.addStretch()
        self.open_button = button("Open Gerber / ZIP", "fa5s.folder-open")
        self.open_button.clicked.connect(self.choose_file)
        self.folder_button = button("Open folder", "fa5s.folder")
        self.folder_button.clicked.connect(self.choose_folder)
        header.addWidget(self.folder_button)
        header.addWidget(self.open_button)
        layout.addLayout(header)

        split = QSplitter()
        layout.addWidget(split, 1)
        self.controls = QWidget()
        sidebar = QVBoxLayout(self.controls)
        sidebar.setContentsMargins(0, 0, 16, 0)
        sidebar.setSpacing(16)
        sidebar.addWidget(label("01  /  BUILD YOUR STACK", "section"))
        intro = label("Set material thicknesses. Preview changes appear immediately.", "muted")
        intro.setWordWrap(True)
        sidebar.addWidget(intro)

        card = QFrame()
        card.setObjectName("card")
        settings_layout = QVBoxLayout(card)
        settings_layout.setContentsMargins(16, 16, 16, 16)
        settings_layout.setSpacing(12)
        self.copper = self.add_thickness(settings_layout, "Copper · all foils", 0.1, [0.050, 0.075, 0.100])
        self.dielectric = self.add_thickness(settings_layout, "Dielectric · total", 1.6, [1.2, 1.5, 1.6])
        note = label("Copper and dielectric are always included.\nInternal foils divide the substrate equally.", "muted")
        note.setWordWrap(True)
        settings_layout.addWidget(note)
        sidebar.addWidget(card)

        sidebar.addWidget(label("SURFACE LAYERS", "section"))
        self.layer_area = QScrollArea()
        self.layer_area.setWidgetResizable(True)
        self.layer_area.setMinimumHeight(130)
        self.layer_container = QWidget()
        self.layer_layout = QVBoxLayout(self.layer_container)
        self.layer_layout.setSizeConstraint(QLayout.SizeConstraint.SetMinAndMaxSize)
        self.layer_layout.setContentsMargins(0, 0, 0, 0)
        self.layer_layout.addWidget(label("Open a board to configure its layers.", "muted"))
        self.layer_layout.addStretch()
        self.layer_area.setWidget(self.layer_container)
        sidebar.addWidget(self.layer_area, 1)
        self.coplanar = button("Align coatings with copper", "fa5s.layer-group")
        self.coplanar.setCheckable(True)
        self.coplanar.setToolTip("Place soldermask and silkscreen at the outer copper base height on both sides. Components may overlap; their thickness stays unchanged.")
        self.coplanar.toggled.connect(self.refresh)
        sidebar.addWidget(self.coplanar)
        self.mode_note = label("Stacked: mask and silk sit above copper.", "muted")
        self.mode_note.setWordWrap(True)
        sidebar.addWidget(self.mode_note)
        self.export_button = button("Export STEP assembly", "fa5s.cube", True)
        self.export_button.setMinimumHeight(48)
        self.export_button.setEnabled(False)
        self.export_button.clicked.connect(self.choose_export)
        sidebar.addWidget(self.export_button)
        sidebar.addWidget(label("Separate, named solids · millimetres", "muted"))
        split.addWidget(self.controls)

        preview_panel = QWidget()
        preview_layout = QVBoxLayout(preview_panel)
        preview_layout.setContentsMargins(8, 0, 0, 0)
        preview_layout.setSpacing(12)
        preview_layout.addWidget(label("02  /  INSPECT YOUR BOARD", "section"))
        self.board_title = label("No board loaded", "boardTitle")
        preview_layout.addWidget(self.board_title)
        self.board_info = label("Gerber + Excellon  ·  Folder or ZIP  ·  1 board per set", "muted")
        preview_layout.addWidget(self.board_info)
        toolbar = QHBoxLayout()
        self.view_mode = QComboBox()
        self.view_mode.addItems(["3D", "2D"])
        self.view_mode.setAccessibleName("Preview mode")
        self.view_mode.currentTextChanged.connect(self.change_view)
        toolbar.addWidget(self.view_mode)
        self.side = QComboBox()
        self.side.addItems(["Top", "Bottom"])
        self.side.setEnabled(False)
        self.side.currentTextChanged.connect(self.change_view)
        toolbar.addWidget(self.side)
        self.explode = button("Explode", "fa5s.layer-group")
        self.explode.setCheckable(True)
        self.explode.toggled.connect(self.change_view)
        toolbar.addWidget(self.explode)
        toolbar.addStretch()
        fit = button("Fit", "fa5s.expand")
        toolbar.addWidget(fit)
        preview_layout.addLayout(toolbar)
        self.preview = BoardPreview()
        fit.clicked.connect(self.preview.fit)
        preview_layout.addWidget(self.preview, 1)
        legend = QHBoxLayout()
        for kind, name in [("copper", "Copper"), ("dielectric", "Dielectric"), ("mask", "Soldermask"), ("silk", "Silkscreen")]:
            legend.addWidget(label(f'<span style="color:{COLORS[kind]}">●</span>  {name}'))
        legend.addStretch()
        preview_layout.addLayout(legend)
        self.notes = button("Import details", "fa5s.info-circle")
        self.notes.setEnabled(False)
        self.notes.clicked.connect(self.show_notes)
        preview_layout.addWidget(self.notes, alignment=Qt.AlignmentFlag.AlignLeft)
        split.addWidget(preview_panel)
        split.setSizes([350, 900])
        split.setChildrenCollapsible(False)
        self.controls.setMinimumWidth(335)
        self.controls.setMaximumWidth(410)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(3)
        self.progress.hide()
        layout.addWidget(self.progress)
        self.statusBar().showMessage("Ready · Open a Gerber set to begin")
        action = QAction(self)
        action.setShortcut(QKeySequence.StandardKey.Open)
        action.triggered.connect(self.choose_file)
        self.addAction(action)
        for widget in (self.copper, self.dielectric):
            widget.valueChanged.connect(self.refresh)

    def add_thickness(self, layout, title, value, presets):
        row = QHBoxLayout()
        row.addWidget(label(title))
        field = spin(value)
        row.addWidget(field)
        layout.addLayout(row)
        buttons = QHBoxLayout()
        for preset in presets:
            item = button(f"{preset:.3f}" if preset < 1 else f"{preset:.1f}")
            item.setToolTip(f"Set {title.lower()} to {preset} mm")
            item.clicked.connect(lambda checked=False, v=preset: field.setValue(v))
            buttons.addWidget(item)
        layout.addLayout(buttons)
        return field

    def choose_file(self):
        if self.task:
            return
        path, _ = QFileDialog.getOpenFileName(self, "Open Gerber (loads companion files) or ZIP", "",
                    "Gerber sets (*.zip *.gbr *.ger *.gtl *.gbl *.gko *.gm1);;All files (*)")
        if path:
            self.open_path(path)

    def choose_folder(self):
        if not self.task:
            path = QFileDialog.getExistingDirectory(self, "Open folder containing one Gerber set")
            if path:
                self.open_path(path)

    def run_task(self, function, success):
        if self.task:
            return
        self.controls.setEnabled(False)
        self.open_button.setEnabled(False)
        self.folder_button.setEnabled(False)
        self.progress.setRange(0, 0)
        self.progress.show()
        self.task = Task(function, self)
        self.task.progress.connect(self.statusBar().showMessage)
        self.task.succeeded.connect(success)
        self.task.failed.connect(self.show_error)
        self.task.finished.connect(self.task_finished)
        self.task.start()

    def task_finished(self):
        task, self.task = self.task, None
        if task:
            task.deleteLater()
        self.controls.setEnabled(True)
        self.open_button.setEnabled(True)
        self.folder_button.setEnabled(True)
        self.export_button.setEnabled(self.board is not None)
        self.progress.hide()

    def open_path(self, path):
        def load(progress):
            board = load_board(path, progress)
            progress("Preparing preview surfaces…")
            cache = {id(board.outline): mesh_template(board.outline)}
            for layer in board.layers:
                cache[id(layer.geometry)] = mesh_template(layer.geometry)
            return board, cache
        self.statusBar().showMessage("Opening Gerber set…")
        self.run_task(load, self.board_loaded)

    def board_loaded(self, result):
        self.board, cache = result
        self.optional.clear()
        while self.layer_layout.count():
            item = self.layer_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.settings = Settings(copper=self.copper.value(), dielectric=self.dielectric.value())
        for layer in sorted(self.board.layers, key=lambda p: (p.side != "top", p.side, p.kind)):
            row = QWidget()
            row.setFixedHeight(46)
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 4, 0, 4)
            check = QCheckBox(layer.name.replace("_", " "))
            check.setChecked(True)
            check.setToolTip(layer.source)
            row_layout.addWidget(check, 1)
            if layer.kind == "copper":
                check.setEnabled(False)
                row_layout.addWidget(label("Required", "muted"))
            else:
                thickness = spin(0.1)
                thickness.setMaximumWidth(120)
                row_layout.addWidget(thickness)
                self.optional[layer.name] = check, thickness
                check.toggled.connect(thickness.setEnabled)
                check.toggled.connect(self.refresh)
                thickness.valueChanged.connect(self.refresh)
            self.layer_layout.addWidget(row)
        self.layer_layout.addStretch()
        self.preview.cache = cache
        self.preview.paths.clear()
        self.board_title.setText(self.board.name)
        self.notes.setEnabled(True)
        self.refresh()
        self.preview.fit()
        self.statusBar().showMessage(f"Loaded {len(self.board.layers)} material layers · Review Import details before export")

    def refresh(self, *_):
        self.mode_note.setText("Aligned: coatings share copper height; solids can overlap." if self.coplanar.isChecked()
                               else "Stacked: mask and silk sit above copper.")
        if not self.board:
            return
        self.settings.copper = self.copper.value()
        self.settings.dielectric = self.dielectric.value()
        self.settings.coplanar = self.coplanar.isChecked()
        for name, (check, thickness) in self.optional.items():
            self.settings.enabled[name] = check.isChecked()
            self.settings.thicknesses[name] = thickness.value()
        self.components = stack_components(self.board, self.settings)
        self.preview.set_components(self.components)
        x0, y0, x1, y1 = self.board.outline.bounds
        height = max(p.z+p.thickness for p in self.components)-min(p.z for p in self.components)
        self.board_info.setText(f"{x1-x0:.2f} × {y1-y0:.2f} mm  ·  {height:.3f} mm stack  ·  {len(self.components)} components")

    def change_view(self, *_):
        self.preview.mode = self.view_mode.currentText()
        self.preview.bottom = self.side.currentText() == "Bottom"
        self.preview.exploded = self.explode.isChecked()
        self.side.setEnabled(self.preview.mode == "2D")
        self.explode.setEnabled(self.preview.mode == "3D")
        self.preview.update()

    def choose_export(self):
        if not self.board or self.task:
            return
        dialog = QFileDialog(self, "Export STEP assembly")
        dialog.setAcceptMode(QFileDialog.AcceptMode.AcceptSave)
        dialog.setNameFilter("STEP assembly (*.step *.stp)")
        dialog.setDefaultSuffix("step")
        dialog.selectFile(f"{self.board.name}.step")
        if dialog.exec():
            path = dialog.selectedFiles()[0]
            parts = list(self.components)
            self.run_task(lambda progress: export_step(parts, path, progress), self.export_done)

    def export_done(self, path):
        self.statusBar().showMessage(f"STEP exported · {path}")
        QMessageBox.information(self, "STEP assembly exported", f"Saved {len(self.components)} named components.\n\n{path}")

    def show_notes(self):
        if self.board:
            message = QMessageBox(self)
            message.setWindowTitle("Import details")
            message.setText("Board interpretation and source layers")
            message.setInformativeText("\n".join(self.board.warnings[:4]))
            message.setDetailedText("\n".join(self.board.warnings) + "\n\n" + "\n".join(f"{layer.name}: {layer.source}" for layer in self.board.layers))
            message.exec()

    def show_error(self, message, details):
        self.statusBar().showMessage("Operation failed · See error details")
        box = QMessageBox(QMessageBox.Icon.Critical, "Could not complete operation", message, parent=self)
        box.setDetailedText(details)
        box.exec()

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() and not self.task:
            event.acceptProposedAction()

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        if urls and urls[0].isLocalFile() and not self.task:
            self.open_path(urls[0].toLocalFile())

    def closeEvent(self, event):
        if self.task:
            self.statusBar().showMessage("Wait for the current import/export to finish before closing.")
            event.ignore()
        else:
            event.accept()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("GerberSTEP")
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    window = MainWindow()
    window.show()
    if len(sys.argv) > 1:
        window.open_path(sys.argv[1])
    sys.exit(app.exec())
