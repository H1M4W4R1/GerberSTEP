# Build natively on Windows or Linux; see scripts/build.py.
from pathlib import Path
import os
import sys
from PyInstaller.utils.hooks import collect_all, collect_data_files, copy_metadata, collect_delvewheel_libs_directory

# Qt uses Windows' ICU API. Unrelated tools on PATH can ship an incompatible
# icuuc.dll with the same name; resolve system DLLs before those tool directories.
if sys.platform == "win32":
    system32 = str(Path(os.environ["SystemRoot"]) / "System32")
    os.environ["PATH"] = system32 + os.pathsep + os.environ.get("PATH", "")

root = Path(SPECPATH)
datas = [(str(root / "gerberstep" / "assets"), "gerberstep/assets"),
         (str(root / "examples" / "demo"), "examples/demo")]
binaries = []
hiddenimports = ["PyQt6.QtSvg", "OpenGL.platform.win32", "OpenGL.platform.glx"]
for package in ("OCP", "gerbonara"):
    data, binary, hidden = collect_all(package)
    datas += data
    binaries += binary
    hiddenimports += hidden
for package in ("qtawesome", "cadquery"):
    datas += collect_data_files(package)
datas += copy_metadata("cadquery")
for directory in ("cadquery_ocp.libs", "vtk.libs"):
    datas, binaries = collect_delvewheel_libs_directory("OCP", libdir_name=directory,
                                                       datas=datas, binaries=binaries)

a = Analysis([str(root / "main.py")], pathex=[str(root)],
             binaries=binaries, datas=datas, hiddenimports=hiddenimports,
             excludes=["PyQt5", "PySide2", "PySide6", "tkinter", "IPython", "pytest"],
             noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name="GerberSTEP",
          debug=False, strip=False, upx=False, console=False,
          icon=str(root / "gerberstep" / "assets" / "logo.ico"))
