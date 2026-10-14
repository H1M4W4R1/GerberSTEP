import os
import sys
import traceback
import re
from dataclasses import replace
from pathlib import Path

os.environ.setdefault("QT_API", "pyqt6")

import qtawesome as qta
from PyQt6.QtCore import QLocale, QThread, Qt, pyqtSignal
from PyQt6.QtGui import QAction, QActionGroup, QIcon, QKeySequence
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFrame,
    QHBoxLayout, QLabel, QLayout, QMainWindow, QMessageBox, QProgressBar, QPushButton,
    QInputDialog, QMenu, QScrollArea, QSplitter, QVBoxLayout, QWidget,
)

from .export import export_step
from .geometry import load_board
from .model import COLORS, MASK_COLORS, SILK_COLORS, FINISH_COLORS, Settings, stack_components
from .stackups import STACKUPS
from .preview import BoardPreview, mesh_template

ASSETS = Path(__file__).parent / "assets"


def configure_windows_identity():
    """Separate this app from the pythonw taskbar group before creating Qt UI."""
    if sys.platform == "win32":
        import ctypes
        function = ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID
        function.argtypes = [ctypes.c_wchar_p]
        function.restype = ctypes.c_long
        result = function("GerberSTEP.Desktop")
        if result != 0:
            raise OSError(f"Could not register Windows application identity: {result:#x}")


def application_icon():
    return QIcon(str(ASSETS / "logo.ico"))

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
    widget.setDecimals(4)
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
        self.export_components = []
        self.optional = {}
        self.layer_checks = {}
        self.setWindowTitle("GerberSTEP · PCB to mechanical assembly")
        self.setWindowIcon(application_icon())
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

        self.appearance = {"mask": "Green", "silk": "White", "copper": "Bare copper"}
        self.stackup = QComboBox()
        self.stackup.setAccessibleName("JLCPCB stackup")
        self.stackup.addItem("Open a board for JLCPCB presets", None)
        self.stackup.setEnabled(False)
        self.apply_stackup_button = button("", "fa5s.sync-alt")
        self.apply_stackup_button.setFixedSize(36, 36)
        self.apply_stackup_button.setStyleSheet("padding: 5px;")
        self.apply_stackup_button.setAccessibleName("Apply JLCPCB thicknesses")
        self.apply_stackup_button.setToolTip("Apply thicknesses from the selected JLCPCB stackup")
        self.apply_stackup_button.setEnabled(False)
        self.apply_stackup_button.clicked.connect(self.apply_stackup)
        self.stackup.setToolTip("Matches imported copper layers. Applies copper and dielectric only; coating thicknesses remain editable. 2L values are nominal estimates; 4L values use published dimensions.")

        sidebar.addWidget(label("LAYERS", "section"))
        self.layer_area = QScrollArea()
        self.layer_area.setWidgetResizable(True)
        self.layer_area.setMinimumHeight(130)
        self.layer_container = QWidget()
        self.layer_layout = QVBoxLayout(self.layer_container)
        self.layer_layout.setSizeConstraint(QLayout.SizeConstraint.SetMinAndMaxSize)
        self.layer_layout.setContentsMargins(0, 0, 14, 0)
        self.layer_layout.addWidget(label("Open a board to configure its layers.", "muted"))
        self.layer_layout.addStretch()
        self.layer_area.setWidget(self.layer_container)
        sidebar.addWidget(self.layer_area, 1)
        stackup_row = QHBoxLayout()
        self.stackup.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.stackup.setMinimumContentsLength(18)
        stackup_row.addWidget(self.stackup, 1)
        stackup_row.addWidget(self.apply_stackup_button)
        sidebar.addLayout(stackup_row)
        plating_row = QHBoxLayout()
        plating_row.addWidget(label("EMS barrel plating (mm)", "muted"))
        self.plating = QDoubleSpinBox()
        self.plating.setDecimals(3)
        self.plating.setRange(0.001, 0.250)
        self.plating.setSingleStep(0.005)
        self.plating.setValue(self.settings.plating)
        self.plating.setToolTip("Copper wall thickness outside the finished round PTH drill. EMS assumes through holes; slots and blind/buried vias are unsupported.")
        self.plating.setEnabled(False)
        self.plating.valueChanged.connect(self.refresh)
        plating_row.addWidget(self.plating)
        sidebar.addLayout(plating_row)
        self.coplanar = button("", "fa5s.layer-group")
        self.coplanar.setFixedSize(48, 48)
        self.coplanar.setAccessibleName("Align coatings with copper")
        self.coplanar.setCheckable(True)
        self.coplanar.setToolTip("Export only: place soldermask and silkscreen at the outer copper base height. The preview keeps the normal stacked layout.")
        self.coplanar.toggled.connect(self.refresh)
        self.export_button = button("Export STEP assembly", "fa5s.cube", True)
        self.export_button.setMinimumHeight(48)
        self.export_button.setEnabled(False)
        self.export_button.clicked.connect(self.choose_export)
        export_row = QHBoxLayout()
        export_row.addWidget(self.coplanar)
        export_row.addWidget(self.export_button, 1)
        sidebar.addLayout(export_row)
        split.addWidget(self.controls)

        preview_panel = QWidget()
        preview_layout = QVBoxLayout(preview_panel)
        preview_layout.setContentsMargins(8, 0, 0, 0)
        preview_layout.setSpacing(12)
        preview_layout.addWidget(label("02  /  INSPECT YOUR BOARD", "section"))
        self.board_title = label("No board loaded", "boardTitle")
        self.board_title.setTextFormat(Qt.TextFormat.PlainText)
        title_row = QHBoxLayout()
        self.rename_button = button("", "fa5s.pencil-alt")
        self.rename_button.setFixedSize(34, 34)
        self.rename_button.setStyleSheet("padding: 5px;")
        self.rename_button.setToolTip("Edit export file name")
        self.rename_button.setAccessibleName("Edit export file name")
        self.rename_button.setEnabled(False)
        self.rename_button.clicked.connect(self.rename_board)
        title_row.addWidget(self.rename_button)
        title_row.addWidget(self.board_title, 1)
        preview_layout.addLayout(title_row)
        self.board_info = label("Gerber + Excellon  ·  Folder or ZIP  ·  1 board per set", "muted")
        preview_layout.addWidget(self.board_info)
        toolbar = QHBoxLayout()
        self.view_mode = QComboBox()
        self.view_mode.addItems(["3D", "2D", "EMS"])
        self.view_mode.setToolTip("EMS: separate copper bodies and plated through-hole barrels for simulation geometry; exports without a manufacturing monolith.")
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
        self.notes = button("", "fa5s.info-circle")
        self.notes.setFixedSize(36, 36)
        self.notes.setStyleSheet("padding: 5px;")
        self.notes.setToolTip("Import details")
        self.notes.setAccessibleName("Import details")
        self.notes.setEnabled(False)
        self.notes.clicked.connect(self.show_notes)
        toolbar.addWidget(self.notes)
        preview_layout.addLayout(toolbar)
        self.preview = BoardPreview()
        fit.clicked.connect(self.preview.fit)
        preview_layout.addWidget(self.preview, 1)
        legend = QHBoxLayout()
        self.legend_labels = {}
        self.appearance_menus = {}
        choices_by_kind = {"copper": FINISH_COLORS, "mask": MASK_COLORS, "silk": SILK_COLORS}
        for kind, name in [("copper", "Copper"), ("dielectric", "Dielectric"), ("mask", "Soldermask"), ("silk", "Silkscreen")]:
            if kind in choices_by_kind:
                entry = QPushButton()
                entry.setCursor(Qt.CursorShape.PointingHandCursor)
                entry.setAccessibleName(f"{name} appearance")
                entry.setToolTip("Choose board finish" if kind == "copper" else f"Choose {name.lower()} color")
                menu = QMenu(entry)
                group = QActionGroup(menu)
                group.setExclusive(True)
                for option in choices_by_kind[kind]:
                    action = menu.addAction(option)
                    action.setCheckable(True)
                    action.setChecked(option == self.appearance[kind])
                    group.addAction(action)
                    action.triggered.connect(lambda checked, k=kind, value=option: self.set_appearance(k, value))
                entry.setMenu(menu)
                self.appearance_menus[kind] = menu
            else:
                entry = QLabel()
            self.legend_labels[kind] = (entry, name)
            legend.addWidget(entry)
        self.update_legend()
        legend.addStretch()
        self.precision = QPushButton()
        self.precision.setAccessibleName("Curve precision")
        self.precision.setCursor(Qt.CursorShape.PointingHandCursor)
        self.precision.setStyleSheet("QPushButton { border: none; padding: 3px 12px 3px 0; background: transparent; color: #8da5c1; } QPushButton::menu-indicator { width: 8px; }")
        self.precision.setToolTip("Maximum curve chord error. Changes rebuild the loaded board; supported STEP arcs and round drill holes remain exact.")
        self.precision_menu = QMenu(self.precision)
        precision_group = QActionGroup(self.precision_menu)
        precision_group.setExclusive(True)
        for name, tolerance in [("Low · 0.10 mm", 0.1), ("Medium · 0.05 mm", 0.05), ("High · 0.01 mm", 0.01)]:
            action = self.precision_menu.addAction(name)
            action.setData(tolerance)
            action.setCheckable(True)
            precision_group.addAction(action)
            action.triggered.connect(lambda checked, value=tolerance: self.set_precision(value))
        self.precision.setMenu(self.precision_menu)
        self.precision_value = 0.05
        self.set_precision(0.05, rebuild=False)
        legend.addWidget(self.precision)
        preview_layout.addLayout(legend)
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

    def choose_file(self):
        if self.task:
            return
        path, _ = QFileDialog.getOpenFileName(self, "Open Gerber (loads companion files) or ZIP", "",
                    "Gerber sets (*.zip *.gbr *.ger *.gtl *.gbl *.gko *.gm1);;All files (*)")
        if path:
            self.open_path(path)

    def rename_board(self):
        if self.board is None or self.task:
            return
        name, accepted = QInputDialog.getText(self, "Export file name", "File name (without .step):", text=self.board.name)
        if not accepted:
            return
        name = name.strip()
        if name.lower().endswith((".step", ".stp")):
            name = name.rsplit(".", 1)[0]
        if (not name or name.endswith((".", " ")) or re.search(r'[<>:"/\\|?*\x00-\x1f]', name)
                or re.match(r"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)", name, re.I)):
            QMessageBox.warning(self, "Invalid file name", "Enter a file name without path separators or reserved filename characters.")
            return
        self.board.name = name
        self.board_title.setText(name)

    def choose_folder(self):
        if not self.task:
            path = QFileDialog.getExistingDirectory(self, "Open folder containing one Gerber set")
            if path:
                self.open_path(path)

    def run_task(self, function, success):
        if self.task:
            return
        self.controls.setEnabled(False)
        for control in (self.stackup, *(self.legend_labels[k][0] for k in self.appearance)):
            control.setEnabled(False)
        self.open_button.setEnabled(False)
        self.folder_button.setEnabled(False)
        self.precision.setEnabled(False)
        self.rename_button.setEnabled(False)
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
        for control in (self.legend_labels[k][0] for k in self.appearance):
            control.setEnabled(True)
        self.stackup.setEnabled(self.stackup.currentData() is not None)
        self.open_button.setEnabled(True)
        self.folder_button.setEnabled(True)
        self.precision.setEnabled(True)
        self.rename_button.setEnabled(self.board is not None)
        if self.board is not None:
            # On a failed rebuild, the controls must still describe the retained board.
            self.set_precision(self.board.tolerance, rebuild=False)
        self.export_button.setEnabled(bool(self.export_components))
        self.progress.hide()

    def set_precision(self, tolerance, *, rebuild=True):
        changed = self.precision_value != tolerance
        self.precision_value = tolerance
        for action in self.precision_menu.actions():
            selected = action.data() == tolerance
            action.setChecked(selected)
            if selected:
                self.precision.setText(f"Precision: {action.text()}")
        if rebuild and changed and self.board is not None and self.board.source_path and self.task is None:
            self.open_path(self.board.source_path, preserve=True)

    def open_path(self, path, preserve=False):
        tolerance = self.precision_value
        def load(progress):
            board = load_board(path, progress, tolerance=tolerance)
            progress("Preparing preview surfaces…")
            cache = {id(board.outline): mesh_template(board.outline)}
            for layer in board.layers:
                cache[id(layer.geometry)] = mesh_template(layer.geometry)
            return board, cache
        self.statusBar().showMessage("Opening Gerber set…")
        self.run_task(load, lambda result: self.board_loaded(result, preserve=preserve))

    def board_loaded(self, result, preserve=False):
        previous_stackup = self.stackup.currentData() if preserve else None
        previous = {name: (check.isChecked(), thickness.value()) for name, (check, thickness) in self.optional.items()} if preserve else {}
        previous_name = self.board.name if preserve and self.board else None
        self.board, cache = result
        if previous_name is not None:
            self.board.name = previous_name
        self.set_precision(self.board.tolerance, rebuild=False)
        self.optional.clear()
        self.layer_checks.clear()
        while self.layer_layout.count():
            item = self.layer_layout.takeAt(0)
            if item.widget():
                item.widget().hide()
                item.widget().deleteLater()
        self.settings = Settings()
        self.stackup.clear()
        for preset in STACKUPS:
            if preset.matches(self.board):
                self.stackup.addItem(preset.name, preset)
        available = self.stackup.count() > 0
        if not available:
            self.stackup.addItem("No matching JLCPCB preset — use manual values", None)
        self.stackup.setEnabled(available)
        self.apply_stackup_button.setEnabled(available)
        nominal_default = self.stackup.findText("JLCPCB 2L · 1.6 mm (nominal)")
        if nominal_default >= 0:
            self.stackup.setCurrentIndex(nominal_default)
        if previous_stackup is not None:
            index = self.stackup.findData(previous_stackup)
            if index >= 0:
                self.stackup.setCurrentIndex(index)
        defaults = stack_components(self.board, replace(self.settings, ems=False))
        dielectrics = [part for part in defaults if part.kind == "dielectric"]
        if dielectrics:
            # Keep the default total at 1.6 mm after spin-box rounding.
            dielectrics[-1].thickness = self.settings.dielectric - sum(
                round(part.thickness, 4) for part in dielectrics[:-1])
        sources = {layer.name: layer.source for layer in self.board.layers}
        self.layer_layout.addWidget(label("TOP TO BOTTOM - thickness per layer", "muted"))
        # Match the physical stack, including every dielectric gap.
        for part in sorted(defaults, key=lambda part: part.z, reverse=True):
            row = QWidget()
            row.setFixedHeight(46)
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 4, 0, 4)
            check = QCheckBox(part.name.replace("_", " "))
            enabled, value = previous.get(part.name, (True, part.thickness))
            check.setChecked(enabled)
            check.setToolTip(sources.get(part.name, "Insulating section; numbered from bottom to top."))
            row_layout.addWidget(check, 1)
            self.layer_checks[part.name] = check
            thickness = spin(value)
            thickness.setEnabled(enabled)
            thickness.setMaximumWidth(120)
            row_layout.addWidget(thickness)
            self.optional[part.name] = check, thickness
            check.toggled.connect(thickness.setEnabled)
            thickness.valueChanged.connect(self.thickness_changed)
            check.toggled.connect(self.refresh)
            self.layer_layout.addWidget(row)
        self.layer_layout.addStretch()
        self.preview.cache = cache
        self.preview.paths.clear()
        self.board_title.setText(self.board.name)
        self.notes.setEnabled(True)
        self.rename_button.setEnabled(True)
        self.refresh()
        if not preserve:
            self.preview.fit()
        self.statusBar().showMessage(f"Loaded {len(self.board.layers)} material layers · Review Import details before export")

    def set_appearance(self, kind, value):
        self.appearance[kind] = value
        self.update_legend()
        self.refresh()

    def update_legend(self):
        colors = dict(COLORS, mask=MASK_COLORS[self.appearance["mask"]],
                      silk=SILK_COLORS[self.appearance["silk"]],
                      copper=FINISH_COLORS[self.appearance["copper"]])
        for kind, (entry, name) in self.legend_labels.items():
            if kind in self.appearance:
                entry.setText(f"●  {name}")
                entry.setStyleSheet(f"QPushButton {{ color: {colors[kind]}; border: none; padding: 3px 12px 3px 0; background: transparent; }} QPushButton::menu-indicator {{ width: 8px; }}")
            else:
                entry.setText(f'<span style="color:{colors[kind]}">●</span>  {name}')

    def thickness_changed(self, *_):
        self.refresh()

    def apply_stackup(self):
        preset = self.stackup.currentData()
        if self.board is None or preset is None:
            return
        for name, value in preset.thicknesses(self.board).items():
            if name in self.optional:
                control = self.optional[name][1]
                control.blockSignals(True)
                control.setValue(value)
                control.blockSignals(False)
        self.refresh()
        self.statusBar().showMessage(f"Applied {preset.name}; copper and dielectric updated. Coatings unchanged.")

    def refresh(self, *_):
        self.settings.ems = self.view_mode.currentText() == "EMS"
        self.settings.plating = self.plating.value()
        self.plating.setEnabled(self.settings.ems)
        self.coplanar.setEnabled(not self.settings.ems)
        self.coplanar.setToolTip("Coating alignment on: exported coatings align with copper. Preview stays stacked."
                                if self.coplanar.isChecked() else
                                "Coating alignment off: coatings stay stacked. Click to align exported coatings with copper.")
        if not self.board:
            return
        self.settings.mask_color = MASK_COLORS[self.appearance["mask"]]
        self.settings.silk_color = SILK_COLORS[self.appearance["silk"]]
        self.settings.finish = self.appearance["copper"]
        self.settings.coplanar = self.coplanar.isChecked()
        self.settings.enabled = {name: check.isChecked() for name, check in self.layer_checks.items()}
        for name, (check, thickness) in self.optional.items():
            self.settings.enabled[name] = check.isChecked()
            self.settings.thicknesses[name] = thickness.value()
        self.components = stack_components(self.board, replace(self.settings, coplanar=False))
        self.export_components = self.components if self.settings.ems else stack_components(self.board, self.settings)
        self.export_button.setEnabled(bool(self.export_components) and self.task is None)
        self.preview.set_components(self.components)
        self.preview.has_board = True
        x0, y0, x1, y1 = self.board.outline.bounds
        height = (max(p.z+p.thickness for p in self.components)-min(p.z for p in self.components)) if self.components else 0
        units = "bodies" if self.settings.ems else "layers"
        self.board_info.setText(f"{x1-x0:.2f} × {y1-y0:.2f} mm  ·  {height:.3f} mm stack  ·  {len(self.components)} {units}  ·  {self.board.tolerance:g} mm precision")

    def change_view(self, *_):
        self.preview.mode = "2D" if self.view_mode.currentText() == "2D" else "3D"
        self.preview.bottom = self.side.currentText() == "Bottom"
        self.preview.exploded = self.explode.isChecked()
        self.side.setEnabled(self.preview.mode == "2D")
        self.explode.setEnabled(self.preview.mode == "3D")
        self.refresh()
        self.preview.sync_view()
        self.preview.update()

    def monolith_available(self):
        return not self.settings.ems and {"copper", "dielectric"}.issubset({part.kind for part in self.export_components})

    def choose_export(self):
        if not self.board or self.task or not self.export_components:
            return
        dialog = QFileDialog(self, "Export STEP assembly")
        dialog.setAcceptMode(QFileDialog.AcceptMode.AcceptSave)
        dialog.setNameFilter("STEP assembly (*.step *.stp)")
        dialog.setDefaultSuffix("step")
        dialog.selectFile(f"{self.board.name}.step")
        if dialog.exec():
            path = dialog.selectedFiles()[0]
            parts = list(self.export_components)
            self.run_task(lambda progress: export_step(parts, path, progress, add_monolith=True), self.export_done)

    def export_done(self, path):
        self.statusBar().showMessage(f"STEP exported · {path}")
        extra = "\nAdded Manufacturing_Monolith: select this body and hide the original layers for machining." if self.monolith_available() else ""
        units = "EMS components" if self.settings.ems else "layer components"
        QMessageBox.information(self, "STEP assembly exported", f"Saved {len(self.export_components)} {units}.{extra}\n\n{path}")

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
    configure_windows_identity()
    app = QApplication(sys.argv)
    app.setApplicationName("GerberSTEP")
    app.setWindowIcon(application_icon())
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    window = MainWindow()
    window.show()
    if len(sys.argv) > 1:
        window.open_path(sys.argv[1])
    sys.exit(app.exec())
