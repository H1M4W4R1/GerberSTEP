"""Simulation geometry: individual foil islands and through-hole copper barrels."""
from dataclasses import replace
import math

from shapely.geometry import Point
from shapely.ops import unary_union
from shapely.strtree import STRtree

from .geometry import polygons
from .model import COLORS, Component, stack_components


def ems_components(board, settings):
    if not math.isfinite(settings.plating) or settings.plating <= 0:
        raise ValueError("EMS plating thickness must be positive and finite.")
    # Derive physical height from the full stack, independent of visibility.
    full = stack_components(board, replace(settings, ems=False, coplanar=False, enabled={}))
    physical = [p for p in full if p.kind in ("copper", "dielectric")]
    bottom = min(p.z for p in physical)
    top = max(p.z + p.thickness for p in physical)
    parts = stack_components(board, replace(settings, ems=False, coplanar=False))
    # Resin occupies the spaces between internal foil traces at the same height.
    inner_names = {layer.name for layer in board.layers
                   if layer.kind == "copper" and layer.side.startswith("inner")}
    if settings.enabled.get("dielectric", True):
        for foil in full:
            if foil.name in inner_names:
                parts.append(replace(foil, name=f"{foil.name}_Dielectric", kind="dielectric",
                                     geometry=board.outline.difference(foil.geometry)))
    holes = [h for h in board.drill_holes if h.plated is True]
    # Bound chord error by plating thickness so thin barrel walls survive preview.
    radius = max((h.radius + settings.plating for h in holes), default=1)
    error = min(board.tolerance, settings.plating / 8)
    segments = max(16, math.ceil(math.pi / (4 * math.acos(max(-1, 1-error/radius)))))
    envelopes = [Point(h.x, h.y).buffer(h.radius + settings.plating, quad_segs=segments)
                 for h in holes]
    clearance = unary_union(envelopes)
    cutters = [replace(h, radius=h.radius + settings.plating) if h.plated is True else h
               for h in board.drill_holes]
    result = []
    for part in parts:
        if part.kind not in ("copper", "dielectric"):
            continue
        geometry = part.geometry.difference(clearance)
        regions = sorted(polygons(geometry), key=lambda p: (*p.bounds, p.area))
        for index, region in enumerate(regions, 1):
            result.append(replace(part, name=f"{part.name}_Body_{index:04d}",
                                  geometry=region, drill_holes=cutters,
                                  color_override=COLORS[part.kind], separate_bodies=True))
    if any(p.kind == "copper" for p in parts):
        for index, (hole, envelope) in enumerate(zip(holes, envelopes), 1):
            ring = envelope.difference(Point(hole.x, hole.y).buffer(hole.radius, quad_segs=segments))
            # Clip against the imported substrate to preserve board edges/cutouts.
            ring = ring.intersection(board.outline)
            if ring.is_empty:
                continue
            result.append(Component(f"Via_Barrel_{index:04d}", "copper", ring,
                                    bottom, top-bottom, board.drill_holes,
                                    ((hole.x, hole.y, hole.radius),
                                     (hole.x, hole.y, hole.radius + settings.plating)),
                                    min(board.tolerance, error), separate_bodies=True))
    result = connected_copper(result)
    dielectric = [p for p in result if p.kind == "dielectric"]
    if dielectric:
        z = min(p.z for p in dielectric)
        height = max(p.z+p.thickness for p in dielectric) - z
        substrate = Component("Dielectric", "dielectric",
                              unary_union([p.geometry for p in dielectric]), z, height,
                              tolerance=min(p.tolerance for p in dielectric),
                              members=tuple(dielectric))
        result = [substrate] + [p for p in result if p.kind != "dielectric"]
    return result


def connected_copper(parts):
    """Group material sharing a face, including transitive connections via barrels."""
    copper = [p for p in parts if p.kind == "copper"]
    tree = STRtree([p.geometry for p in copper])
    parents = list(range(len(copper)))

    def root(i):
        while parents[i] != i:
            parents[i] = parents[parents[i]]
            i = parents[i]
        return i

    for i, a in enumerate(copper):
        for j in tree.query(a.geometry):
            if j <= i:
                continue
            b = copper[j]
            overlap_z = min(a.z+a.thickness, b.z+b.thickness) - max(a.z, b.z)
            if overlap_z < -1e-9:
                continue
            contact = a.geometry.intersection(b.geometry)
            if contact.area > 1e-12 or (overlap_z > 1e-9 and contact.length > 1e-9):
                parents[root(j)] = root(i)
    groups = {}
    for i, part in enumerate(copper):
        groups.setdefault(root(i), []).append(part)
    result = [p for p in parts if p.kind != "copper"]
    for index, members in enumerate(groups.values(), 1):
        z = min(p.z for p in members)
        height = max(p.z+p.thickness for p in members) - z
        result.append(Component(f"Copper_Body_{index:04d}", "copper",
                                unary_union([p.geometry for p in members]), z, height,
                                tolerance=min(p.tolerance for p in members),
                                separate_bodies=True, members=tuple(members)))
    return result
