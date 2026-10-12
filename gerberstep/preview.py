"""Cached GPU 3D and vector 2D previews; software path for headless QA."""
import math

import numpy as np
from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QImage, QPainter, QPainterPath, QPen, QPolygonF
from PyQt6.QtWidgets import QApplication, QWidget
from shapely import constrained_delaunay_triangles

from .geometry import polygons


def mesh_template(geometry):
    """Unit-height watertight surface triangles, including hole walls."""
    triangles = []
    for poly in polygons(geometry):
        for triangle in constrained_delaunay_triangles(poly).geoms:
            xy = list(triangle.exterior.coords)[:3]
            triangles.append([(x, y, 1) for x, y in xy])
            triangles.append([(x, y, 0) for x, y in reversed(xy)])
        for ring in (poly.exterior, *poly.interiors):
            for a, b in zip(ring.coords, list(ring.coords)[1:]):
                triangles.append([(*a, 0), (*b, 0), (*b, 1)])
                triangles.append([(*a, 0), (*b, 1), (*a, 1)])
    return np.array(triangles, dtype=float).reshape((-1, 3, 3))


def rasterize(triangles, colors, width, height):
    """Orthographic depth buffer: per-pixel depth avoids intersecting-face artifacts."""
    pixels = np.zeros((height, width, 4), dtype=np.uint8)
    depth = np.full((height, width), -np.inf, dtype=np.float32)
    for triangle, color in zip(triangles, colors):
        xmin, ymin = np.maximum(np.floor(triangle[:, :2].min(axis=0)).astype(int), 0)
        xmax, ymax = np.minimum(np.ceil(triangle[:, :2].max(axis=0)).astype(int), [width-1, height-1])
        if xmin > xmax or ymin > ymax:
            continue
        a, b, c = triangle
        denominator = (b[1]-c[1])*(a[0]-c[0]) + (c[0]-b[0])*(a[1]-c[1])
        if abs(denominator) < 1e-10:
            continue
        yy, xx = np.ogrid[ymin:ymax+1, xmin:xmax+1]
        u = ((b[1]-c[1])*(xx+0.5-c[0]) + (c[0]-b[0])*(yy+0.5-c[1])) / denominator
        v = ((c[1]-a[1])*(xx+0.5-c[0]) + (a[0]-c[0])*(yy+0.5-c[1])) / denominator
        w = 1-u-v
        z = u*a[2] + v*b[2] + w*c[2]
        region = depth[ymin:ymax+1, xmin:xmax+1]
        visible = (u >= -1e-8) & (v >= -1e-8) & (w >= -1e-8) & (z >= region-1e-7)
        region[visible] = z[visible]
        tile = pixels[ymin:ymax+1, xmin:xmax+1]
        tile[visible, :3] = color
        tile[visible, 3] = 255
    return pixels


class BoardPreview(QWidget):
    def __init__(self):
        super().__init__()
        self.setMinimumSize(420, 340)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.parts = []
        self.has_board = False
        self.cache = {}
        self.paths = {}
        self.mode = "3D"
        self.bottom = False
        self.exploded = False
        self.yaw, self.pitch = -0.45, 0.8
        self.zoom = 1.0
        self.pan = QPointF()
        self.last = None
        self.center = np.zeros(3)
        self.span = 60.0
        self.gpu = None
        # Qt's headless platforms do not support QOpenGLWidget. Keep software
        # rendering for screenshots/tests; interactive desktop uses retained GL.
        if QApplication.platformName() not in ("offscreen", "minimal"):
            from .gpu_preview import GPUPreview
            self.gpu = GPUPreview(self)
            self.gpu.hide()

    def set_components(self, parts, cache=None, reset=False):
        self.parts = parts
        if cache is not None:
            self.cache = cache
            self.paths.clear()
        if parts:
            bounds = np.array([p.geometry.bounds for p in parts])
            lo, hi = bounds[:, :2].min(axis=0), bounds[:, 2:].max(axis=0)
            self.center = np.array([*(lo+hi)/2, 0])
            self.span = max(*(hi-lo), 1)
            for part in parts:
                key = id(part.geometry)
                if key not in self.paths:
                    path = QPainterPath()
                    path.setFillRule(Qt.FillRule.OddEvenFill)
                    for poly in polygons(part.geometry):
                        for ring in (poly.exterior, *poly.interiors):
                            path.addPolygon(QPolygonF([QPointF(x, y) for x, y in ring.coords]))
                    self.paths[key] = path
        if reset:
            self.fit()
        self.sync_view()
        self.update()

    def sync_view(self):
        if self.gpu is not None:
            self.gpu.set_scene(self.parts, self.cache, self.center, self.span, self.exploded)
            self.gpu.setVisible(self.mode == "3D" and bool(self.parts))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.gpu is not None:
            self.gpu.setGeometry(self.rect())

    def fit(self):
        self.zoom, self.pan = 1.0, QPointF()
        self.yaw, self.pitch = -0.45, 0.8
        if self.gpu is not None:
            self.gpu.fit()
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#0c1422"))
        painter.setPen(QPen(QColor("#1c2a3d"), 1))
        for x in range(24, self.width(), 28):
            for y in range(24, self.height(), 28):
                painter.drawPoint(x, y)
        if not self.parts:
            painter.setPen(QColor("#e1eafd"))
            painter.setFont(QFont("Inter", 21, QFont.Weight.DemiBold))
            painter.drawText(self.rect().adjusted(20, -28, -20, -28), Qt.AlignmentFlag.AlignCenter,
                             "No layers selected." if self.has_board else "Your board, in another dimension.")
            painter.setFont(QFont("Inter", 11))
            painter.setPen(QColor("#8193ac"))
            painter.drawText(self.rect().adjusted(20, 55, -20, 55), Qt.AlignmentFlag.AlignCenter,
                             "Enable a layer to preview and export it." if self.has_board else "Open a Gerber folder or ZIP to preview every layer.")
            return
        scale = min(self.width(), self.height()) * 0.72 / self.span * self.zoom
        origin = QPointF(self.width()/2, self.height()/2) + self.pan
        if self.mode == "2D":
            painter.save()
            painter.translate(origin)
            painter.scale(-scale if self.bottom else scale, -scale)
            painter.translate(-self.center[0], -self.center[1])
            painter.setPen(Qt.PenStyle.NoPen)
            for part in sorted(self.parts, key=lambda p: p.z, reverse=self.bottom):
                painter.setBrush(QColor(part.color))
                painter.drawPath(self.paths[id(part.geometry)])
            painter.restore()
        elif self.gpu is None:
            cy, sy = math.cos(self.yaw), math.sin(self.yaw)
            cp, sp = math.cos(self.pitch), math.sin(self.pitch)
            rotate = np.array([[cy, -sy, 0], [sy*sp, cy*sp, cp], [-sy*cp, -cy*cp, sp]])
            all_triangles, all_colors = [], []
            for index, part in enumerate(sorted(self.parts, key=lambda p: p.z)):
                mesh = self.cache.get(id(part.geometry))
                if mesh is None or not len(mesh):
                    continue
                verts = mesh.copy()
                verts[:, :, 2] *= part.thickness
                verts[:, :, 2] += part.z + (index * self.span * 0.055 if self.exploded else 0)
                verts -= self.center
                verts = verts @ rotate.T
                normals = np.cross(verts[:, 1]-verts[:, 0], verts[:, 2]-verts[:, 0])
                normals /= np.maximum(np.linalg.norm(normals, axis=1, keepdims=True), 1e-12)
                light = 0.55 + 0.45 * np.abs(normals @ np.array([0.25, 0.4, 0.88]))
                color = QColor(part.color)
                colors = np.clip(light[:, None]*[color.red(), color.green(), color.blue()], 0, 255).astype(int)
                all_triangles.append(verts)
                all_colors.append(colors)
            if all_triangles:
                triangles = np.concatenate(all_triangles)
                colors = np.concatenate(all_colors)
                triangles[:, :, 0] = origin.x() + triangles[:, :, 0]*scale
                triangles[:, :, 1] = origin.y() - triangles[:, :, 1]*scale
                pixels = rasterize(triangles, colors, self.width(), self.height())
                rendered = QImage(pixels.data, self.width(), self.height(), self.width()*4, QImage.Format.Format_RGBA8888)
                painter.drawImage(0, 0, rendered)
        painter.setPen(QColor("#8193ac"))
        painter.setFont(QFont("Inter", 9))
        hint = "Drag to orbit  ·  Right-drag to pan  ·  Scroll to zoom" if self.mode == "3D" else "Drag to pan  ·  Scroll to zoom"
        painter.drawText(QRectF(20, self.height()-35, self.width()-40, 25), Qt.AlignmentFlag.AlignLeft, hint)
        if self.exploded and self.mode == "3D":
            painter.setPen(QColor("#65bcff"))
            painter.drawText(20, 30, "EXPLODED VIEW  /  export keeps actual heights")

    def mousePressEvent(self, event):
        self.last = event.position()

    def mouseMoveEvent(self, event):
        if self.last is None or not event.buttons():
            return
        delta = event.position()-self.last
        self.last = event.position()
        if self.mode == "3D" and event.buttons() & Qt.MouseButton.LeftButton:
            self.yaw += delta.x()*0.009
            self.pitch = max(-math.pi/2, min(math.pi/2, self.pitch+delta.y()*0.009))
        else:
            self.pan += delta
        self.update()

    def mouseReleaseEvent(self, event):
        self.last = None

    def wheelEvent(self, event):
        self.zoom = max(0.15, min(25, self.zoom * 1.15**(event.angleDelta().y()/120)))
        self.update()

    def mouseDoubleClickEvent(self, event):
        self.fit()
