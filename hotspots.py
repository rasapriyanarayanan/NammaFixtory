"""Geospatial hotspot clustering (DBSCAN with haversine metric)."""
import numpy as np
from sklearn.cluster import DBSCAN

EARTH_R = 6371000.0


def hotspots(points, eps_m=80, min_samples=3):
    """points: list of dicts with lat, lon. Returns list of clusters (centre, size)."""
    if len(points) < min_samples:
        return []
    coords = np.radians([[p["lat"], p["lon"]] for p in points])
    labels = DBSCAN(eps=eps_m / EARTH_R, min_samples=min_samples, metric="haversine",
                    algorithm="ball_tree").fit(coords).labels_
    out = []
    for lab in sorted(set(labels) - {-1}):
        idx = [i for i, l in enumerate(labels) if l == lab]
        out.append({
            "cluster": int(lab),
            "size": len(idx),
            "lat": float(np.mean([points[i]["lat"] for i in idx])),
            "lon": float(np.mean([points[i]["lon"] for i in idx])),
            "radius_m": eps_m,
        })
    return sorted(out, key=lambda c: -c["size"])
