"""Build separate B-rep components and atomically write a STEP assembly."""
import os
import tempfile
from pathlib import Path

from .geometry import polygons


def build_assembly(components, progress=lambda message: None, *, add_monolith=True):
    import cadquery as cq

    assembly = cq.Assembly(name="GerberSTEP")
    manufacturing_solids = []
    for index, part in enumerate(components):
        progress(f"Creating solid {index+1}/{len(components)} · {part.name}")
        solids = []
        for poly in polygons(part.geometry):
            def wire(ring):
                return cq.Wire.makePolygon([cq.Vector(x, y, part.z) for x, y in list(ring.coords)[:-1]], close=True)
            solid = cq.Solid.extrudeLinear(wire(poly.exterior), [wire(ring) for ring in poly.interiors],
                                          cq.Vector(0, 0, part.thickness))
            if not solid.isValid():
                raise ValueError(f"Invalid solid in {part.name}. Check the source Gerber geometry.")
            solids.append(solid)
        if part.kind in ("copper", "dielectric"):
            manufacturing_solids.extend(solids)
        if solids:
            rgb = tuple(int(part.color[i:i+2], 16)/255 for i in (1, 3, 5))
            assembly.add(cq.Compound.makeCompound(solids), name=part.name, color=cq.Color(*rgb))
    if add_monolith:
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
