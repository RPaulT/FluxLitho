import os, zipfile, tempfile, io, builtins, math
from pathlib import Path

from shapely import affinity
from shapely import ops as sops
from shapely import geometry as sgeom

# --- Monkeypatch: 'rU' Mode für alte pcb-tools abfangen ---
_orig_io_open = io.open
_orig_builtin_open = builtins.open

def _patched_open(file, mode='r', *args, **kwargs):
    if isinstance(mode, str) and 'U' in mode:
        mode = mode.replace('U', '')
    return _orig_io_open(file, mode, *args, **kwargs)

def _patched_builtin_open(file, mode='r', *args, **kwargs):
    if isinstance(mode, str) and 'U' in mode:
        mode = mode.replace('U', '')
    return _orig_builtin_open(file, mode, *args, **kwargs)

io.open = _patched_open
builtins.open = _patched_builtin_open

# pcb-tools
try:
    from gerber import load_layer
    from gerber.primitives import Region, Circle, Rectangle, Line  # optional
except Exception:
    load_layer = None
    Region = Circle = Rectangle = Line = object

# --- Defaults ---
DEFAULT_TRACE_WIDTH = 0.25  # mm, falls keine width angegeben
DEFAULT_PAD_SIZE   = 0.80   # mm, Fallback für Pads ohne Dimensionen


def collect_gerber_files(path: str):
    """Sammelt alle Gerber-Dateien aus Einzeldatei oder ZIP"""
    files = []
    tempdir = None
    try:
        if path.lower().endswith(".zip"):
            tempdir = tempfile.mkdtemp(prefix="gerber_")
            with zipfile.ZipFile(path, "r") as zf:
                zf.extractall(tempdir)
            for root, _, fnames in os.walk(tempdir):
                for fn in fnames:
                    if fn.lower().endswith((
                        ".gbr", ".ger", ".gtl", ".gbl", ".gto", ".gbo",
                        ".gts", ".gbs", ".gtp", ".gbp", ".gko", ".gml", ".gdl"
                    )):
                        files.append(os.path.join(root, fn))
        else:
            files = [path]
    except Exception as e:
        print(f"❌ ZIP Fehler: {e}")
    return files, tempdir


def safe_load_layer(path):
    """Versucht load_layer() mit/ohne file_format, je nach API-Version"""
    if load_layer is None:
        raise RuntimeError("pcb-tools nicht installiert.")
    try:
        return load_layer(path)
    except TypeError:
        return load_layer(path, file_format='rs274x')


def _rectangle_or_obround_from_bbox(prim, unit_scale):
    """
    Baut ein Rechteck/Obround über prim.bounding_box() inkl. Rotation & Loch.
    Funktioniert zuverlässiger als nur position/width/height.
    """
    # Bounding Box (in Layer-Einheiten)
    try:
        minx, miny, maxx, maxy = prim.bounding_box()
    except Exception:
        # Fallback auf position/width/height
        (cx, cy) = prim.position
        w = getattr(prim, "width", DEFAULT_PAD_SIZE)
        h = getattr(prim, "height", DEFAULT_PAD_SIZE)
        minx, maxx = cx - w/2, cx + w/2
        miny, maxy = cy - h/2, cy + h/2

    # In mm skalieren
    minx, miny, maxx, maxy = (minx * unit_scale, miny * unit_scale,
                              maxx * unit_scale, maxy * unit_scale)

    cx = (minx + maxx) * 0.5
    cy = (miny + maxy) * 0.5
    w  = (maxx - minx)
    h  = (maxy - miny)

    # Grundform
    pad = sgeom.box(minx, miny, maxx, maxy)

    # Obround? (falls Attribut vorhanden)
    if prim.__class__.__name__ == "Obround":
        rad = min(w, h) * 0.5
        # Ein obround lässt sich durch Aufdicken der Box realisieren
        pad = pad.buffer(rad, cap_style=2, join_style=2)

    # Rotation (um Pad-Mittelpunkt)
    angle = getattr(prim, "rotation", 0) or 0
    if angle:
        pad = affinity.rotate(pad, angle, origin=(cx, cy))

    # Loch ausstanzen, falls vorhanden
    hole_diam = getattr(prim, "hole_diameter", 0) or 0
    if hole_diam > 0:
        hr = (hole_diam * unit_scale) * 0.5
        hole = sgeom.Point(cx, cy).buffer(hr, resolution=32)
        pad = pad.difference(hole)

    return pad


def _prim_to_geom(prim, unit_scale):
    polys = []
    ptype = prim.__class__.__name__

    try:
        # --- Kreisförmige Pads ---
        if ptype == "Circle":
            if hasattr(prim, "flashed") and prim.flashed is False:
                return polys
            (cx, cy) = prim.position if isinstance(prim.position, tuple) else (prim.position.x, prim.position.y)
            cx, cy = cx * unit_scale, cy * unit_scale
            r = (prim.diameter * unit_scale) * 0.5
            pad = sgeom.Point(cx, cy).buffer(r, resolution=32)

            # Loch
            hole_d = getattr(prim, "hole_diameter", 0) or 0
            if hole_d > 0:
                hole = sgeom.Point(cx, cy).buffer((hole_d * unit_scale) * 0.5, resolution=32)
                pad = pad.difference(hole)

            polys.append(pad)

        # --- Rechtecke (über bounding_box) ---
        elif ptype == "Rectangle":
            if hasattr(prim, "flashed") and prim.flashed is False:
                return polys
            polys.append(_rectangle_or_obround_from_bbox(prim, unit_scale))

        # --- Obround (über bounding_box) ---
        elif ptype == "Obround":
            polys.append(_rectangle_or_obround_from_bbox(prim, unit_scale))

        # --- Tracks / Lines ---
        elif ptype in ("Line", "Track"):
            (x1, y1) = prim.start
            (x2, y2) = prim.end
            x1, y1 = x1 * unit_scale, y1 * unit_scale
            x2, y2 = x2 * unit_scale, y2 * unit_scale

            width = getattr(prim, "width", None)
            if not width or width <= 0:
                width = DEFAULT_TRACE_WIDTH
            width *= unit_scale

            line = sgeom.LineString([(x1, y1), (x2, y2)])
            # cap_style=2 (rund) erzeugt PCB-typische Enden
            polys.append(line.buffer(width * 0.5, cap_style=2, join_style=2))

        # --- Region (gefüllte Polygone) ---
        elif ptype == "Region":
            verts = getattr(prim, "vertices", None)
            if verts and len(verts) >= 3:
                pts = [(x * unit_scale, y * unit_scale) for (x, y) in verts]
                poly = sgeom.Polygon(pts)
                if poly.is_valid:
                    polys.append(poly)

        # --- Arc (als dicker Bogen) ---
        elif ptype == "Arc":
            (cx, cy) = prim.center
            r = prim.radius * unit_scale
            start_angle = prim.start_angle
            end_angle   = prim.end_angle
            w = getattr(prim, "width", DEFAULT_TRACE_WIDTH) * unit_scale

            if end_angle < start_angle:
                end_angle += 360
            steps = 48
            angles = [math.radians(start_angle + (end_angle - start_angle) * i / steps)
                      for i in range(steps + 1)]
            pts = [(cx * unit_scale + r * math.cos(a), cy * unit_scale + r * math.sin(a))
                   for a in angles]
            arc_line = sgeom.LineString(pts)
            polys.append(arc_line.buffer(w * 0.5, cap_style=2, join_style=2))

        # --- AMGroup (verschachtelte Prims) ---
        elif ptype == "AMGroup":
            for sub in getattr(prim, "primitives", []):
                polys.extend(_prim_to_geom(sub, unit_scale))

        # --- Outline (nur zur Vorschau – dünn puffern) ---
        elif ptype == "Outline":
            segs = []
            for sub in getattr(prim, "primitives", []):
                if sub.__class__.__name__ in ("Line", "Track"):
                    (x1, y1) = sub.start
                    (x2, y2) = sub.end
                    segs.append(((x1 * unit_scale, y1 * unit_scale),
                                 (x2 * unit_scale, y2 * unit_scale)))
            if segs:
                ml = sgeom.MultiLineString(segs)
                polys.append(ml.buffer(0.05, cap_style=2, join_style=2))  # 0.05 mm Preview

        # unbekannte Typen: still ignorieren
    except Exception as e:
        print(f"⚠ Fehler bei Primitive {prim}: {e}")

    return polys


def gerber_layer_to_shapely(layer):
    polys = []
    unit_scale = 25.4 if getattr(layer, "units", None) == "inch" else 1.0

    for prim in getattr(layer, "primitives", []):
        polys.extend(_prim_to_geom(prim, unit_scale))

    if not polys:
        print("⚠ Keine Geometrien erzeugt in diesem Layer!")
        return None

    return sops.unary_union(polys)


def load_gerber_files(files, selected_names):
    """Lädt die ausgewählten Gerber-Dateien in eine kombinierte Shapely-Geometrie"""
    if load_layer is None:
        print("❌ pcb-tools nicht installiert.")
        return None

    geoms = []
    for f in files:
        if Path(f).name not in selected_names:
            continue
        try:
            layer = safe_load_layer(f)
            geom = gerber_layer_to_shapely(layer)
            if geom:
                geoms.append(geom)
        except Exception as e:
            print(f"⚠ Fehler {f}: {e}")

    if not geoms:
        return None

    combined = sops.unary_union(geoms)

    # Auf (0,0) normalisieren und spiegeln wie zuvor
    minx, miny, _, _ = combined.bounds
    combined = affinity.translate(combined, xoff=-minx, yoff=-miny)
    combined = affinity.scale(combined, xfact=-1, yfact=-1, origin=(0, 0))
    minx, miny, _, _ = combined.bounds
    combined = affinity.translate(combined, xoff=-minx, yoff=-miny)

    return combined