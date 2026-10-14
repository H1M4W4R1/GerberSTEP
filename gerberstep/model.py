from dataclasses import dataclass, field
import math

from shapely.geometry.base import BaseGeometry


COLORS = {
    "copper": "#db9959", "dielectric": "#465570",
    "mask": "#178e77", "silk": "#e4eefc",
}


@dataclass
class Layer:
    name: str
    kind: str
    side: str
    geometry: BaseGeometry
    source: str = ""
    circles: tuple[tuple[float, float, float], ...] = ()


@dataclass
class DrillHole:
    """Exact Excellon drill location and radius, in millimetres."""

    x: float
    y: float
    radius: float


@dataclass
class Board:
    name: str
    outline: BaseGeometry
    layers: list[Layer]
    warnings: list[str] = field(default_factory=list)
    tolerance: float = 0.01
    source_path: str = ""
    drill_holes: list[DrillHole] = field(default_factory=list)
    outline_circles: tuple[tuple[float, float, float], ...] = ()


@dataclass
class Settings:
    copper: float = 0.100
    dielectric: float = 1.600
    thicknesses: dict[str, float] = field(default_factory=dict)
    enabled: dict[str, bool] = field(default_factory=dict)
    coplanar: bool = False


@dataclass
class Component:
    name: str
    kind: str
    geometry: BaseGeometry
    z: float
    thickness: float
    drill_holes: list[DrillHole] = field(default_factory=list)
    circles: tuple[tuple[float, float, float], ...] = ()
    tolerance: float = 0.01

    @property
    def color(self):
        return COLORS[self.kind]


def stack_components(board: Board, settings: Settings) -> list[Component]:
    """Z=0 is substrate bottom. Substrate thickness excludes internal copper.

    Each internal foil adds its thickness to the finished stack. Optional layers
    grow outward on either side; coplanar mode shares the outer copper base Z.
    """
    if settings.copper <= 0 or settings.dielectric <= 0:
        raise ValueError("Copper and dielectric thickness must be positive.")
    copper = [layer for layer in board.layers if layer.kind == "copper"]
    inner = sorted(
        [layer for layer in copper if layer.side.startswith("inner")],
        key=lambda layer: int(layer.side[5:]), reverse=True,
    )
    gap = settings.dielectric / (len(inner) + 1)
    def layer_thickness(name, default):
        value = settings.thicknesses.get(name, default)
        if not math.isfinite(value) or value <= 0:
            raise ValueError(f"{name}: thickness must be positive and finite.")
        return value

    parts = []
    z = 0.0
    for index in range(len(inner) + 1):
        name = f"Dielectric_{index + 1}"
        depth = layer_thickness(name, gap)
        parts.append(Component(name, "dielectric", board.outline, z, depth))
        z += depth
        if index < len(inner):
            layer = inner[index]
            depth = layer_thickness(layer.name, settings.copper)
            parts.append(Component(layer.name, "copper", layer.geometry, z, depth))
            z += depth
    for layer in copper:
        if layer.side in ("top", "bottom"):
            depth = layer_thickness(layer.name, settings.copper)
            parts.append(Component(layer.name, "copper", layer.geometry,
                                   z if layer.side == "top" else -depth, depth))
    for side in ("top", "bottom"):
        foil = next((layer for layer in copper if layer.side == side), None)
        base = z if side == "top" else 0.0
        depth = layer_thickness(foil.name, settings.copper) if foil else 0
        cursor = base + (depth if side == "top" else -depth)
        for kind in ("mask", "silk"):
            for layer in board.layers:
                if layer.side != side or layer.kind != kind or not settings.enabled.get(layer.name, True):
                    continue
                thickness = settings.thicknesses.get(layer.name, 0.1)
                if thickness <= 0:
                    raise ValueError(f"{layer.name}: thickness must be positive.")
                if settings.coplanar:
                    start = base if side == "top" else base - thickness
                else:
                    start = cursor if side == "top" else cursor - thickness
                    cursor += thickness if side == "top" else -thickness
                parts.append(Component(layer.name, kind, layer.geometry, start, thickness))
    layer_circles = {layer.name: layer.circles for layer in board.layers}
    for part in parts:
        part.drill_holes = board.drill_holes
        part.circles = board.outline_circles + layer_circles.get(part.name, ())
        part.tolerance = board.tolerance
    return [part for part in parts if not part.geometry.is_empty
            and settings.enabled.get(part.name, True)
            and (part.kind != "dielectric" or settings.enabled.get("dielectric", True))]
