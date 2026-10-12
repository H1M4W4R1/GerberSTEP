"""Build a native portable folder. Run with the project's build environment."""
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
subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm",
                "--distpath", str(root / "dist" / target),
                "--workpath", str(root / "build" / target),
                str(root / "GerberSTEP.spec")], cwd=root, env=environment, check=True)
print(f"Portable app: {root / 'dist' / target / 'GerberSTEP'}")
archive = shutil.make_archive(str(root / "dist" / f"GerberSTEP-{target}"),
                              "zip" if target == "windows" else "gztar",
                              root_dir=root / "dist" / target, base_dir="GerberSTEP")
print(f"Archive: {archive}")
