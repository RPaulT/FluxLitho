import math
import trimesh
from shapely.geometry import Polygon, MultiPolygon
from constants import PANEL_MM_W, PANEL_MM_H, FRAME_HEIGHT_MM

def extrude_with_engine(geom, height: float):
    kwargs = {"engine": "earcut"}
    meshes = []
    if isinstance(geom, Polygon):
        try:
            return trimesh.creation.extrude_polygon(geom, height, **kwargs)
        except Exception:
            return trimesh.creation.extrude_polygon(geom, height)
    elif isinstance(geom, MultiPolygon):
        for g in geom.geoms:
            try:
                m = trimesh.creation.extrude_polygon(g, height, **kwargs)
            except Exception:
                m = trimesh.creation.extrude_polygon(g, height)
            meshes.append(m)
        return trimesh.util.concatenate(meshes)
    else:
        raise ValueError("Geometrie ist weder Polygon noch MultiPolygon")

def build_and_transform_mesh(geom, offset_x, offset_y):
    from shapely import affinity
    frame_poly = Polygon([
        (0, 0), (PANEL_MM_W, 0),
        (PANEL_MM_W, PANEL_MM_H), (0, PANEL_MM_H)
    ])
    geom = affinity.translate(geom, xoff=offset_x, yoff=offset_y)
    negative = frame_poly.difference(geom)
    mesh = extrude_with_engine(negative, FRAME_HEIGHT_MM)

    # Drehung + Verschiebung
    rot270 = trimesh.transformations.rotation_matrix(
        angle=math.radians(270), direction=[0, 0, 1], point=[0, 0, 0])
    mesh.apply_transform(rot270)
    xmin, ymin, zmin = mesh.bounds[0]
    mesh.apply_translation([-xmin, -ymin, -zmin])
    return mesh