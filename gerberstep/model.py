from dataclasses import dataclass, field

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


@dataclass
class Board:
    name: str
    outline: BaseGeometry
    layers: list[Layer]
    warnings: list[str] = field(default_factory=list)
    tolerance: float = 0.01
    source_path: str = ""


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
    parts = []
    z = 0.0
    for index in range(len(inner) + 1):
        parts.append(Component(f"Dielectric_{index + 1}", "dielectric", board.outline, z, gap))
        z += gap
        if index < len(inner):
            layer = inner[index]
            parts.append(Component(layer.name, "copper", layer.geometry, z, settings.copper))
            z += settings.copper
    for layer in copper:
        if layer.side in ("top", "bottom"):
            parts.append(Component(layer.name, "copper", layer.geometry,
                                   z if layer.side == "top" else -settings.copper, settings.copper))
    for side in ("top", "bottom"):
        has_copper = any(layer.side == side for layer in copper)
        base = z if side == "top" else 0.0
        cursor = base + (settings.copper if side == "top" else -settings.copper) if has_copper else base
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
    return [part for part in parts if not part.geometry.is_empty]
