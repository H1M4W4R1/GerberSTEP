"""Convert Gerbonara primitives to millimetre planar geometry."""
import copy
import math
import re
import warnings
from pathlib import Path

from gerbonara import LayerStack
from gerbonara import graphic_primitives as gp
from gerbonara.utils import MM, approximate_arc
from shapely import make_valid, set_precision
from shapely.geometry import GeometryCollection, LineString, Point, Polygon
from shapely.ops import polygonize_full, unary_union

from .model import Board, Layer

TOLERANCE = 0.01  # maximum curve chord error in mm


def polygons(geometry):
    if geometry.geom_type == "Polygon":
        if geometry.area > 1e-12:
            yield geometry
    elif hasattr(geometry, "geoms"):
        for part in geometry.geoms:
            yield from polygons(part)


def clean(geometry):
    return unary_union(list(polygons(make_valid(geometry))))


def curve_segments(radius, tolerance):
    if not math.isfinite(tolerance) or tolerance <= 0:
        raise ValueError("Curve tolerance must be a positive finite number.")
    minimum = 8 if tolerance <= TOLERANCE else 2
    return max(minimum, math.ceil(math.pi / (4 * math.acos(max(-1, 1-tolerance/radius)))))


def primitive_geometry(primitive, tolerance=TOLERANCE):
    # Handle rectangles ourselves: rotation must act on each corner separately.
    if isinstance(primitive, gp.Rectangle):
        c, s = math.cos(primitive.rotation), math.sin(primitive.rotation)
        return Polygon([(primitive.x + x*c - y*s, primitive.y + x*s + y*c)
                        for x, y in [(-primitive.w/2, -primitive.h/2),
                                     (primitive.w/2, -primitive.h/2),
                                     (primitive.w/2, primitive.h/2),
                                     (-primitive.w/2, primitive.h/2)]])
    if isinstance(primitive, gp.Circle):
        if primitive.r <= 0:
            return GeometryCollection()
        n = curve_segments(primitive.r, tolerance)
        return Point(primitive.x, primitive.y).buffer(primitive.r, quad_segs=n)
    if isinstance(primitive, (gp.Line, gp.Arc)):
        if primitive.width <= 0:
            return GeometryCollection()
        radius = primitive.width / 2
        n = curve_segments(radius, tolerance/2)
        if isinstance(primitive, gp.Arc):
            points = list(approximate_arc(primitive.cx, primitive.cy, primitive.x1,
                          primitive.y1, primitive.x2, primitive.y2, primitive.clockwise,
                          max_error=tolerance/2))
        else:
            points = [(primitive.x1, primitive.y1), (primitive.x2, primitive.y2)]
        return LineString(points).buffer(radius, quad_segs=n)
    points = primitive.to_arc_poly().approximate_arcs(max_error=tolerance).outline
    return clean(Polygon(points)) if len(points) >= 3 else GeometryCollection()


def layer_geometry(cam, tolerance=TOLERANCE):
    """Compose flashes locally so aperture holes do not erase prior artwork."""
    result = GeometryCollection()
    pending = []
    for obj in cam.objects:
        positive = copy.copy(obj)
        positive.polarity_dark = True
        shape = GeometryCollection()
        for primitive in positive.to_primitives(MM):
            geom = primitive_geometry(primitive, tolerance)
            shape = shape.union(geom) if primitive.polarity_dark else shape.difference(geom)
        if obj.polarity_dark:
            pending.append(shape)
        else:
            if pending:
                result = result.union(unary_union(pending))
                pending.clear()
            result = result.difference(shape)
    return clean(result.union(unary_union(pending)))


def board_outline(cam, tolerance=TOLERANCE):
    segments, regions = [], []
    for obj in cam.objects:
        for primitive in obj.to_primitives(MM):
            if isinstance(primitive, gp.Line):
                segments.append(LineString([(primitive.x1, primitive.y1), (primitive.x2, primitive.y2)]))
            elif isinstance(primitive, gp.Arc):
                points = list(approximate_arc(primitive.cx, primitive.cy, primitive.x1,
                              primitive.y1, primitive.x2, primitive.y2, primitive.clockwise,
                              max_error=tolerance))
                segments.append(LineString(points))
            else:
                regions.append(primitive_geometry(primitive, tolerance))
    outline = GeometryCollection()
    if segments:
        faces, cuts, dangles, invalid = polygonize_full(unary_union([
            set_precision(segment, 0.00001) for segment in segments]))
        if not cuts.is_empty or not dangles.is_empty or not invalid.is_empty:
            raise ValueError("Board outline has open or intersecting contours. Export a closed Edge.Cuts/outline layer.")
        # Polygonize returns nested faces; XOR their exterior rings preserves cutouts.
        rings = {Polygon(face.exterior).wkb: Polygon(face.exterior) for face in faces.geoms}
        for ring in rings.values():
            outline = outline.symmetric_difference(ring)
    for region in regions:
        outline = outline.symmetric_difference(region)
    outline = clean(outline)
    if outline.is_empty:
        raise ValueError("No closed board outline found. Include a board outline Gerber.")
    return outline


def load_board(path: str, progress=lambda message: None, *, tolerance=TOLERANCE) -> Board:
    if not math.isfinite(tolerance) or tolerance <= 0:
        raise ValueError("Curve tolerance must be a positive finite number.")
    source = Path(path)
    if source.is_file() and source.suffix.lower() != ".zip":
        source = source.parent  # selecting one Gerber loads its companion files
    progress("Reading fabrication files…")
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        try:
            stack = LayerStack.open(source)
        except ValueError as exc:
            raise ValueError("Could not identify the fabrication layers. Include copper and a closed board outline "
                             "with standard Gerber filenames, and keep one board per folder/ZIP. "
                             f"Parser details: {exc}") from exc
        if stack.outline is None:
            raise ValueError("Missing board outline. Include a .gko, .gm1 or Edge_Cuts.gbr file in the Gerber folder.")
        outline = board_outline(stack.outline.instance, tolerance)
        holes = unary_union([layer_geometry(drill.instance, tolerance) for drill in stack.drill_layers])
        substrate = clean(outline.difference(holes))
        layers = []
        notes = []
        for (side, kind), cam in stack.graphic_layers.items():
            if kind not in ("copper", "mask", "silk"):
                if kind != "outline":
                    notes.append(f"Excluded {side} {kind}: not a board material layer.")
                continue
            if side not in ("top", "bottom") and not (kind == "copper" and re.fullmatch(r"inner\d+", side)):
                raise ValueError(f"Unrecognized layer position: {side} {kind}.")
            progress(f"Building {side} {kind}…")
            instance = cam.instance
            original = getattr(instance, "original_path", None)
            if original and Path(original).exists() and re.search(r"%IPNEG\*%", Path(original).read_text(errors="replace")):
                raise ValueError(f"{Path(original).name}: legacy negative-image Gerber is unsupported. Re-export as RS-274X positive image.")
            geom = layer_geometry(instance, tolerance)
            if kind == "mask":
                geom = outline.difference(geom)  # standard mask Gerbers describe openings
            geom = clean(geom.intersection(substrate))
            name = f"{side.title()}_{dict(copper='Copper', mask='Soldermask', silk='Silkscreen')[kind]}"
            if geom.is_empty:
                notes.append(f"{name}: no material inside the board; no STEP component will be created.")
            layers.append(Layer(name, kind, side, geom, Path(original).name if original else ""))
        if not any(layer.kind == "copper" for layer in layers):
            raise ValueError("No copper layers recognized. Use standard names such as .gtl/.gbl or F_Cu.gbr/B_Cu.gbr.")
        if substrate.is_empty:
            raise ValueError("The board outline is empty after drill subtraction.")
        notes.extend(str(item.message) for item in caught)
        notes.append(f"Soldermask files are interpreted as openings. Curves use a {tolerance:g} mm chord tolerance.")
        return Board(stack.board_name or source.stem, substrate, layers, list(dict.fromkeys(notes)), tolerance, str(source.resolve()))
