"""Recover circular STEP edges only from circles recorded in the source Gerber."""
import math

from shapely.geometry import Point, Polygon, box
from shapely.strtree import STRtree


class CircularWires:
    def __init__(self, circles, tolerance):
        self.circles = tuple(sorted(set(circles)))
        self.tolerance = tolerance
        self.epsilon = 1e-7  # source-coordinate matching, not a fitting tolerance
        self.tree = STRtree([box(x-r-self.epsilon, y-r-self.epsilon,
                                 x+r+self.epsilon, y+r+self.epsilon)
                             for x, y, r in self.circles])

    def _matches(self, point):
        return {int(i) for i in self.tree.query(Point(point))
                if abs(math.dist(point, self.circles[i][:2]) - self.circles[i][2])
                <= self.epsilon}

    def wire(self, ring, z):
        import cadquery as cq

        points = list(ring.coords)[:-1]
        count = len(points)
        matches = [self._matches(p) for p in points]
        labels = []
        for i, a in enumerate(points):
            b = points[(i+1) % count]
            label = None
            for candidate in sorted(matches[i] & matches[(i+1) % count]):
                x, y, r = self.circles[candidate]
                u, v = (a[0]-x, a[1]-y), (b[0]-x, b[1]-y)
                angle = math.atan2(u[0]*v[1]-u[1]*v[0], u[0]*v[0]+u[1]*v[1])
                # Reject diameters/long straight chords and preserve winding.
                if (1e-10 < abs(angle) < math.pi - 1e-8
                        and r*(1-math.cos(angle/2)) <= self.tolerance + self.epsilon):
                    label = (candidate, 1 if angle > 0 else -1)
                    break
            labels.append(label)
        if count >= 5 and labels[0] is not None and all(l == labels[0] for l in labels):
            x, y, r = self.circles[labels[0][0]]
            proxy = self._sample(x, y, r, 0, labels[0][1]*2*math.pi)
            return cq.Wire.makeCircle(r, cq.Vector(x, y, z), cq.Vector(0, 0, 1)), proxy, True

        # Begin at a transition so a circular run spanning the ring seam stays whole.
        start = next((i for i in range(count) if labels[i] != labels[i-1]), 0)
        points = points[start:] + points[:start]
        labels = labels[start:] + labels[:start]
        points.append(points[0])
        edges, proxy, changed = [], [], False
        i = 0
        while i < count:
            end = i+1
            while end < count and labels[end] == labels[i]:
                end += 1
            if labels[i] is not None and end-i >= 3:
                x, y, r = self.circles[labels[i][0]]
                angle = math.atan2(points[i][1]-y, points[i][0]-x)
                sweep = sum(math.atan2(
                    (a[0]-x)*(b[1]-y)-(a[1]-y)*(b[0]-x),
                    (a[0]-x)*(b[0]-x)+(a[1]-y)*(b[1]-y))
                    for a, b in zip(points[i:end], points[i+1:end+1]))
                middle = cq.Vector(x+r*math.cos(angle+sweep/2), y+r*math.sin(angle+sweep/2), z)
                edges.append(cq.Edge.makeThreePointArc(cq.Vector(*points[i], z), middle,
                                                       cq.Vector(*points[end], z)))
                proxy.extend(self._sample(x, y, r, angle, sweep)[:-1])
                changed = True
            else:
                for a, b in zip(points[i:end], points[i+1:end+1]):
                    edges.append(cq.Edge.makeLine(cq.Vector(*a, z), cq.Vector(*b, z)))
                    proxy.append(a)
            i = end
        return cq.Wire.assembleEdges(edges), proxy, changed

    def _sample(self, x, y, radius, angle, sweep):
        # Fine planar proxy to reject self-crossings before creating a solid.
        error = min(1e-5, self.tolerance / 20)
        step = 2*math.acos(max(-1, 1-error/radius))
        count = max(4, math.ceil(abs(sweep)/max(step, 1e-6)))
        return [(x+radius*math.cos(angle+sweep*i/count),
                 y+radius*math.sin(angle+sweep*i/count)) for i in range(count+1)]

    def solid(self, polygon, z, thickness):
        import cadquery as cq

        outer, proxy, changed = self.wire(polygon.exterior, z)
        inner_results = [self.wire(ring, z) for ring in polygon.interiors]
        changed |= any(result[2] for result in inner_results)
        if not changed:
            return None
        planar = Polygon(proxy, [result[1] for result in inner_results])
        if not planar.is_valid or planar.is_empty:
            return None
        solid = cq.Solid.extrudeLinear(outer, [result[0] for result in inner_results],
                                      cq.Vector(0, 0, thickness))
        return solid if solid.isValid() and len(solid.Solids()) == 1 else None
