"""Build a native standalone executable. Run with the project's build environment."""
import os
import platform
import subprocess
import sys
import shutil
from pathlib import Path

root = Path(__file__).resolve().parents[1]
target = {"Windows": "windows", "Linux": "linux"}.get(platform.system())
if target is None:
    raise SystemExit("Supported build hosts: Windows and Linux.")
environment = dict(os.environ, QT_API="pyqt6")
# Keep the packaging cache inside the workspace as well.
environment["PYINSTALLER_CONFIG_DIR"] = str(root / "build" / "pyinstaller-cache")
subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
                "--distpath", str(root / "dist" / target),
                "--workpath", str(root / "build" / target),
                str(root / "GerberSTEP.spec")], cwd=root, env=environment, check=True)
executable = "GerberSTEP.exe" if target == "windows" else "GerberSTEP"
print(f"Standalone app: {root / 'dist' / target / executable}")
archive = shutil.make_archive(str(root / "dist" / f"GerberSTEP-{target}"),
                              "zip" if target == "windows" else "gztar",
                              root_dir=root / "dist" / target, base_dir=executable)
print(f"Archive: {archive}")
