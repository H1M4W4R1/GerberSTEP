"""Build the Windows multi-resolution icon from the editable SVG logo."""
import os
import struct
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtCore import QBuffer, QIODevice, Qt
from PyQt6.QtGui import QImage, QPainter
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtWidgets import QApplication


def main():
    app = QApplication.instance() or QApplication([])
    assets = Path(__file__).resolve().parents[1] / "gerberstep" / "assets"
    renderer = QSvgRenderer(str(assets / "logo.svg"))
    sizes = (16, 24, 32, 48, 64, 128, 256)
    images = []
    for size in sizes:
        image = QImage(size, size, QImage.Format.Format_ARGB32)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        renderer.render(painter)
        painter.end()
        buffer = QBuffer()
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        image.save(buffer, "PNG")
        images.append(bytes(buffer.data()))
    offset = 6 + 16*len(sizes)
    entries = []
    for size, data in zip(sizes, images):
        entries.append(struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(data), offset))
        offset += len(data)
    (assets / "logo.ico").write_bytes(struct.pack("<HHH", 0, 1, len(sizes)) + b"".join(entries) + b"".join(images))


if __name__ == "__main__":
    main()
