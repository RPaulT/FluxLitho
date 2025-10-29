import math
import numpy as np
from shapely.geometry import Polygon, MultiPolygon
from shapely.ops import unary_union
from shapely import affinity
from svgpathtools import svg2paths
from PySide6.QtCore import QPointF
from PySide6.QtGui import QPainterPath

def path_to_polyline(path, spacing=1.0):
    length = max(path.length(), 1e-6)
    n = max(8, int(math.ceil(length / spacing)))
    ts = np.linspace(0.0, 1.0, n)
    pts = [path.point(t) for t in ts]
    coords = [(p.real, p.imag) for p in pts]
    if abs(coords[0][0] - coords[-1][0]) > 1e-6 or abs(coords[0][1] - coords[-1][1]) > 1e-6:
        coords.append(coords[0])
    return coords

def svg_to_polygon(svg_file, target_width_mm=None):
    paths, _ = svg2paths(svg_file)
    polys = []
    for p in paths:
        coords = path_to_polyline(p, spacing=1.0)
        if len(coords) < 3:
            continue
        poly = Polygon(coords)
        if not poly.is_valid:
            poly = poly.buffer(0)
        if poly.is_empty or poly.area <= 0:
            continue
        polys.append(poly)

    if not polys:
        return None

    merged = unary_union(polys)

    if target_width_mm is not None:
        minx, miny, maxx, maxy = merged.bounds
        width = max(maxx - minx, 1e-6)
        scale = float(target_width_mm) / float(width)
        merged = affinity.translate(merged, xoff=-minx, yoff=-miny)
        merged = affinity.scale(merged, xfact=scale, yfact=scale, origin=(0, 0))

    return merged

def shapely_to_qpath(geom):
    path = QPainterPath()
    def add_poly(poly: Polygon):
        exterior = poly.exterior
        if exterior is None: return
        coords = list(exterior.coords)
        if not coords: return
        path.moveTo(QPointF(coords[0][0], coords[0][1]))
        for (x, y) in coords[1:]:
            path.lineTo(QPointF(x, y))
        path.closeSubpath()
        for interior in poly.interiors:
            icoords = list(interior.coords)
            if not icoords: continue
            path.moveTo(QPointF(icoords[0][0], icoords[0][1]))
            for (x, y) in icoords[1:]:
                path.lineTo(QPointF(x, y))
            path.closeSubpath()
    if isinstance(geom, Polygon):
        add_poly(geom)
    elif isinstance(geom, MultiPolygon):
        for g in geom.geoms: add_poly(g)
    return path