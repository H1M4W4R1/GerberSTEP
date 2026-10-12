"""Build separate B-rep components and atomically write a STEP assembly."""
import os
import tempfile
from pathlib import Path

from .geometry import polygons
from .curves import CircularWires


def component_solids(part):
    """Use source arcs when they preserve valid, separate material regions."""
    import cadquery as cq
    from shapely.geometry import box
    from shapely.strtree import STRtree

    regions = list(polygons(part.geometry))

    def faceted(poly):
        def wire(ring):
            return cq.Wire.makePolygon([cq.Vector(x, y, part.z)
                                       for x, y in list(ring.coords)[:-1]], close=True)
        return cq.Solid.extrudeLinear(wire(poly.exterior), [wire(r) for r in poly.interiors],
                                      cq.Vector(0, 0, part.thickness))

    curves = CircularWires(part.circles, part.tolerance) if part.circles else None
    solids, recovered = [], []
    for poly in regions:
        solid = None
        if curves:
            try:
                solid = curves.solid(poly, part.z, part.thickness)
            except (ValueError, RuntimeError):
                # Ambiguous intersections keep the original polygon boundaries.
                pass
        recovered.append(solid is not None)
        solids.append(solid if solid is not None else faceted(poly))

    if any(recovered) and len(solids) > 1:
        margin = part.tolerance + 1e-7
        tree = STRtree([box(p.bounds[0]-margin, p.bounds[1]-margin,
                            p.bounds[2]+margin, p.bounds[3]+margin) for p in regions])
        for i, solid in enumerate(solids):
            bounds = solid.BoundingBox()
            neighbors = tree.query(box(bounds.xmin, bounds.ymin, bounds.xmax, bounds.ymax))
            if any(j > i and (recovered[i] or recovered[j])
                   and solid.distance(solids[j]) <= 1e-7 for j in neighbors):
                # Never close a gap or merge separate artwork islands by recovering arcs.
                solids = [faceted(poly) for poly in regions]
                break
    if any(not solid.isValid() for solid in solids):
        raise ValueError(f"Invalid solid in {part.name}. Check the source Gerber geometry.")
    return solids


def build_assembly(components, progress=lambda message: None, *, add_monolith=True):
    import cadquery as cq

    assembly = cq.Assembly(name="GerberSTEP")
    if not components:
        raise ValueError("Select at least one non-empty layer to export.")
    manufacturing_solids = []
    for index, part in enumerate(components):
        progress(f"Creating solid {index+1}/{len(components)} · {part.name}")
        solids = component_solids(part)
        if solids and part.drill_holes:
            # Preview holes are inscribed polygons. Cutting the exact source
            # cylinders removes the remaining facets without filling artwork
            # gaps, slots, overlapping drills or holes crossing the board edge.
            xmin, ymin, xmax, ymax = part.geometry.bounds
            cutters = [cq.Solid.makeCylinder(
                hole.radius, part.thickness + 2,
                cq.Vector(hole.x, hole.y, part.z - 1))
                for hole in part.drill_holes
                if hole.x + hole.radius > xmin and hole.x - hole.radius < xmax
                and hole.y + hole.radius > ymin and hole.y - hole.radius < ymax]
            if cutters:
                drilled = cq.Compound.makeCompound(solids).cut(*cutters).clean()
                if not drilled.isValid():
                    raise ValueError(f"Invalid drilled solid in {part.name}.")
                solids = drilled.Solids()
        if part.kind in ("copper", "dielectric"):
            manufacturing_solids.extend(solids)
        if solids:
            rgb = tuple(int(part.color[i:i+2], 16)/255 for i in (1, 3, 5))
            assembly.add(cq.Compound.makeCompound(solids), name=part.name, color=cq.Color(*rgb))
    if add_monolith and {"copper", "dielectric"}.issubset({p.kind for p in components}):
        progress("Fusing copper and dielectric into the manufacturing monolith…")
        if not manufacturing_solids:
            raise ValueError("No copper/dielectric solids are available for the manufacturing monolith.")
        monolith = manufacturing_solids[0]
        if len(manufacturing_solids) > 1:
            monolith = monolith.fuse(*manufacturing_solids[1:])
        monolith = monolith.clean()
        if not monolith.isValid() or len(monolith.Solids()) != 1:
            raise ValueError("Copper and dielectric do not form one connected solid. "
                             "Disable 'Add manufacturing monolith' to export separate layers, "
                             "or supply one connected board.")
        assembly.add(monolith.Solids()[0], name="Manufacturing_Monolith", color=cq.Color(0.55, 0.65, 0.78))
    return assembly


def export_step(components, path, progress=lambda message: None, *, add_monolith=True):
    assembly = build_assembly(components, progress, add_monolith=add_monolith)
    target = Path(path)
    handle, temporary = tempfile.mkstemp(suffix=".step", dir=target.parent)
    os.close(handle)
    try:
        progress("Writing STEP assembly…")
        assembly.export(temporary, exportType="STEP", mode="default")
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return str(target)
