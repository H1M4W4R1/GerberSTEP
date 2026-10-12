"""Retained OpenGL scene: camera movement never rebuilds board geometry."""
import math
import numpy as np
from OpenGL import GL
from PyQt6.QtGui import QColor, QMatrix4x4, QVector3D
from pyqtgraph.opengl import GLMeshItem, GLViewWidget, MeshData


class GPUPreview(GLViewWidget):
    def __init__(self, parent=None):
        super().__init__(parent=parent)
        surface = self.format()
        surface.setDepthBufferSize(24)
        surface.setSamples(4)
        self.setFormat(surface)
        self.setBackgroundColor("#0c1422")
        self.setToolTip("Drag to orbit · Middle-drag to pan · Scroll to zoom · Double-click to fit")
        self.mesh_items = {}
        self.span = 60.0
        self.scene_center = np.zeros(3)
        self.mesh_builds = 0
        self.scene_height = 1.0

    def set_scene(self, parts, templates, center, span, exploded):
        self.span = span
        self.scene_center = center
        self.scene_height = max((abs(p.z)+p.thickness for p in parts), default=1) + (len(parts)*span*0.055 if exploded else 0)
        active = {part.name for part in parts}
        for name in list(self.mesh_items):
            if name not in active:
                _, item = self.mesh_items.pop(name)
                self.removeItem(item)
        for index, part in enumerate(sorted(parts, key=lambda p: p.z)):
            key = id(part.geometry)
            previous_key, item = self.mesh_items.get(part.name, (None, None))
            if previous_key != key:
                if item is not None:
                    self.removeItem(item)
                vertices = np.asarray(templates[key], dtype=np.float32)
                normals = np.cross(vertices[:, 1]-vertices[:, 0], vertices[:, 2]-vertices[:, 0])
                normals /= np.maximum(np.linalg.norm(normals, axis=1, keepdims=True), 1e-12)
                light = 0.55 + 0.45*np.abs(normals @ np.array([0.25, 0.4, 0.88]))
                color = QColor(part.color)
                colors = np.ones((len(vertices), 4), dtype=np.float32)
                colors[:, :3] = light[:, None]*[color.redF(), color.greenF(), color.blueF()]
                mesh = MeshData(vertexes=vertices)
                # Constructor treats colors as already face-indexed when faces
                # are omitted. Expand one color per face via the explicit API.
                mesh.setFaceColors(colors)
                item = GLMeshItem(meshdata=mesh, smooth=False, computeNormals=False,
                                  drawEdges=False, glOptions="opaque")
                self.addItem(item)
                self.mesh_items[part.name] = key, item
                self.mesh_builds += 1
            # The original unit-height vertex buffers survive thickness and
            # exploded-view changes. Only the model matrix changes.
            item.resetTransform()
            item.scale(1, 1, part.thickness)
            item.translate(-center[0], -center[1], part.z + (index*span*0.055 if exploded else 0))
        self.update()

    def projectionMatrix(self, region, viewport):
        # The general-purpose viewer's million-to-one clipping range loses
        # precision between thin PCB layers, particularly on 16-bit depth buffers.
        x, y, width, height = viewport
        distance = self.opts["distance"]
        near = max(0.001, distance*0.05)
        far = distance + 4*self.span + 2*self.scene_height
        right = near*math.tan(math.radians(self.opts["fov"])/2)
        top = right*height/width
        matrix = QMatrix4x4()
        matrix.frustum(right*((region[0]-x)*2/width-1),
                       right*((region[0]+region[2]-x)*2/width-1),
                       top*((region[1]-y)*2/height-1),
                       top*((region[1]+region[3]-y)*2/height-1), near, far)
        return matrix

    def paintGL(self):
        GL.glDepthMask(GL.GL_TRUE)
        GL.glDepthFunc(GL.GL_LEQUAL)
        super().paintGL()

    def fit(self):
        self.opts["center"] = QVector3D(0, 0, 0)
        self.setCameraPosition(distance=self.span*1.8, elevation=35, azimuth=-55)

    def mouseDoubleClickEvent(self, event):
        self.fit()
