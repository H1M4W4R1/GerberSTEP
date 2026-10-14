"""Convert Gerbonara primitives to millimetre planar geometry."""
import copy
import math
import re
import warnings
from pathlib import Path

from gerbonara import LayerStack
from gerbonara import graphic_primitives as gp
from gerbonara.utils import MM, approximate_arc
from shapely import make_valid, set_precision, snap
from shapely.geometry import GeometryCollection, LineString, MultiPoint, Point, Polygon
from shapely.ops import polygonize_full, unary_union

from .model import Board, DrillHole, Layer

TOLERANCE = 0.01  # maximum curve chord error in mm
OUTLINE_GAP = 0.05  # mm; independent of preview curve precision


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


def circular_boundaries(cam, *, outline=False):
    """Source circles for conservative STEP arc recovery, never fitted guesses."""
    circles = set()
    for obj in cam.objects:
        for p in obj.to_primitives(MM):
            if isinstance(p, gp.Circle):
                circles.add((p.x, p.y, p.r))
            elif isinstance(p, gp.Line):
                if not outline:
                    circles.update(((p.x1, p.y1, p.width / 2),
                                    (p.x2, p.y2, p.width / 2)))
            elif isinstance(p, gp.Arc):
                radius = math.hypot(p.x1 - p.cx, p.y1 - p.cy)
                if outline:
                    circles.add((p.cx, p.cy, radius))
                else:
                    circles.update(((p.cx, p.cy, radius + p.width / 2),
                                    (p.cx, p.cy, radius - p.width / 2),
                                    (p.x1, p.y1, p.width / 2),
                                    (p.x2, p.y2, p.width / 2)))
            elif isinstance(p, gp.ArcPoly):
                for start, end, (clockwise, center) in p.segments:
                    if clockwise is not None:
                        circles.add((*center, math.dist(start, center)))
    return tuple(sorted(c for c in circles if c[2] > 0))


def outline_faces(segments, stroke_width=0):
    """Node intersections, then bridge only uniquely paired loose endpoints."""
    linework = unary_union([set_precision(segment, 0.00001) for segment in segments])
    faces, cuts, dangles, invalid = polygonize_full(linework)
    if cuts.is_empty and dangles.is_empty and invalid.is_empty:
        return faces, cuts, dangles, invalid

    lines = list(linework.geoms) if hasattr(linework, "geoms") else [linework]
    degree = {}
    for line in lines:
        if line.is_empty:
            continue
        for point in (line.coords[0], line.coords[-1]):
            degree[point] = degree.get(point, 0) + 1
    endpoints = [point for point, count in degree.items() if count == 1]
    # Spatial bins keep fragmented outlines from requiring all-pairs searches.
    bins = {}
    for i, (x, y) in enumerate(endpoints):
        bins.setdefault((math.floor(x / OUTLINE_GAP), math.floor(y / OUTLINE_GAP)), []).append(i)
    neighbors = []
    for point in endpoints:
        bx, by = (math.floor(value / OUTLINE_GAP) for value in point)
        neighbors.append([j for dx in (-1, 0, 1) for dy in (-1, 0, 1)
                          for j in bins.get((bx + dx, by + dy), [])
                          if 0 < math.dist(point, endpoints[j]) <= OUTLINE_GAP])
    bridges = [LineString([endpoints[i], endpoints[js[0]]])
               for i, js in enumerate(neighbors)
               if len(js) == 1 and js[0] > i and neighbors[js[0]] == [i]]
    if bridges:
        repaired = unary_union([linework, *bridges])
        recovered = polygonize_full(repaired)
        # Do not retain bridges that fail to contribute to any closed face.
        boundaries = unary_union([face.boundary for face in recovered[0].geoms])
        bridges = [bridge for bridge in bridges if boundaries.covers(bridge)]
        if bridges:
            faces, cuts, dangles, invalid = polygonize_full(unary_union([linework, *bridges]))
            warnings.warn(f"Board outline repaired: bridged {len(bridges)} gap(s) up to "
                          f"{OUTLINE_GAP:g} mm. Verify the outline before export.", stacklevel=2)
    if faces.is_empty and stroke_width > 0:
        # Some exporters draw overlapping, slightly offset edge strokes. Their
        # ink touches, but their centerlines do not. Snap to source vertices,
        # including vertices near segment interiors, without offsetting the board
        # by buffering the stroke. Cap repair distance even for wide apertures.
        distance = min(stroke_width, 0.5)
        reference = MultiPoint([point for line in lines for point in line.coords])
        repaired = unary_union([snap(line, reference, distance) for line in lines])
        recovered = polygonize_full(repaired)
        if not recovered[0].is_empty and all(part.is_empty for part in recovered[1:]):
            faces, cuts, dangles, invalid = recovered
            warnings.warn("Board outline repaired by snapping overlapping edge strokes "
                          f"within {distance:g} mm (limited by the outline aperture width). "
                          "Verify the outline dimensions and cutouts before export.", stacklevel=2)
    return faces, cuts, dangles, invalid


def board_outline(cam, tolerance=TOLERANCE):
    segments, regions = [], []
    stroke_widths = []
    for obj in cam.objects:
        for primitive in obj.to_primitives(MM):
            if isinstance(primitive, gp.Line):
                stroke_widths.append(primitive.width)
                segments.append(LineString([(primitive.x1, primitive.y1), (primitive.x2, primitive.y2)]))
            elif isinstance(primitive, gp.Arc):
                stroke_widths.append(primitive.width)
                points = list(approximate_arc(primitive.cx, primitive.cy, primitive.x1,
                              primitive.y1, primitive.x2, primitive.y2, primitive.clockwise,
                              max_error=tolerance))
                segments.append(LineString(points))
            else:
                regions.append(primitive_geometry(primitive, tolerance))
    outline = GeometryCollection()
    unused_length = 0
    if segments:
        # Region outlines already provide boundaries; do not reshape their lines.
        width = min(stroke_widths) if stroke_widths and not regions else 0
        faces, cuts, dangles, invalid = outline_faces(segments, width)
        unused_length = cuts.length + dangles.length + invalid.length
        # Polygonize returns nested faces; XOR their exterior rings preserves cutouts.
        rings = {Polygon(face.exterior).wkb: Polygon(face.exterior) for face in faces.geoms}
        for ring in rings.values():
            outline = outline.symmetric_difference(ring)
    for region in regions:
        outline = outline.symmetric_difference(region)
    outline = clean(outline)
    if outline.is_empty:
        raise ValueError("No closed board outline found: contours are open or degenerate. "
                         f"Repair of small gaps (up to {OUTLINE_GAP:g} mm) and overlapping "
                         "edge strokes could not recover a boundary. "
                         "Export a closed Edge.Cuts/outline layer.")
    if unused_length:
        warnings.warn(f"Board outline recovered from closed contours; ignored {unused_length:g} mm "
                      "of open or unused outline lines. Open cutouts may be missing. "
                      "Verify the outline and cutouts before export.", stacklevel=2)
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
        drill_layers = [drill.instance for drill in stack.drill_layers]
        holes = unary_union([layer_geometry(drill, tolerance) for drill in drill_layers])
        # Preserve source circles independently of the polygonized preview.
        # Routed slots remain polygons; never infer drills from artwork/cutouts.
        drill_holes = [DrillHole(p.x, p.y, p.r, obj.plated)
                       for drill in drill_layers for obj in drill.objects
                       for p in obj.to_primitives(MM)
                       if isinstance(p, gp.Circle) and p.polarity_dark and p.r > 0]
        substrate = clean(outline.difference(holes))
        layers = []
        notes = []
        if any(h.plated is None for h in drill_holes):
            notes.append("EMS: holes with unknown plating are left unplated; supply explicit PTH/NPTH drill metadata.")
        notes.append("EMS assumes round plated drills are finished through holes. Blind/buried vias and plated slots are not modeled; plating thickness is user supplied.")
        for (side, kind), cam in stack.graphic_layers.items():
            # Gerbonara's EasyEDA rules use inner_1; the stack model uses inner1.
            side = re.sub(r"^inner_(\d+)$", r"inner\1", side)
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
            layers.append(Layer(name, kind, side, geom, Path(original).name if original else "",
                                circular_boundaries(instance)))
        if not any(layer.kind == "copper" for layer in layers):
            raise ValueError("No copper layers recognized. Use standard names such as .gtl/.gbl or F_Cu.gbr/B_Cu.gbr.")
        if substrate.is_empty:
            raise ValueError("The board outline is empty after drill subtraction.")
        notes.extend(str(item.message) for item in caught)
        notes.append(f"Soldermask files are interpreted as openings. Preview curves use a {tolerance:g} mm chord tolerance. "
                     "STEP restores supported source arcs and exact round drills.")
        name = source.stem if source.is_file() and source.suffix.lower() == ".zip" else stack.board_name or source.stem
        return Board(name, substrate, layers, list(dict.fromkeys(notes)), tolerance,
                     str(source.resolve()), drill_holes,
                     circular_boundaries(stack.outline.instance, outline=True))
