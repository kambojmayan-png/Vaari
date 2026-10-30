#!/usr/bin/env python3
"""Load a GeoJSON FeatureCollection with request_id properties and attach polygons to plots."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db import get_session_factory  # noqa: E402  (after the sys.path line above)
from app.enums import to_x100  # noqa: E402  (after the sys.path line above)
from app.evidence.area import acres_of_polygon, centroid_of_polygon  # noqa: E402  (after the sys.path line above)
from app.models import Plot, Request  # noqa: E402  (after the sys.path line above)


def load_plots_from_geojson(file_path: Path) -> int:
    data = json.loads(file_path.read_text(encoding="utf-8"))
    features = data.get("features") if data.get("type") == "FeatureCollection" else [data]

    sf = get_session_factory()
    updated_count = 0
    with sf() as session:
        for feat in features:
            props = feat.get("properties") or {}
            req_id = props.get("request_id")
            geom = feat.get("geometry")
            if req_id is None or geom is None:
                continue

            req = session.query(Request).filter_by(id=int(req_id)).first()
            if req is None:
                print(f"Skipping request_id={req_id}: request not found.")
                continue

            plot = session.query(Plot).filter_by(id=req.plot_id).first()
            if plot is None:
                continue

            geom_str = json.dumps(geom)
            computed_acres = acres_of_polygon(geom_str)
            c_lat, c_lon = centroid_of_polygon(geom_str)

            plot.geojson = geom_str
            plot.acres_x100 = to_x100(computed_acres)
            plot.centroid_lat = c_lat
            plot.centroid_lon = c_lon
            plot.location_source = "polygon"
            updated_count += 1
            print(
                f"Attached polygon to request #{req.id} (plot #{plot.id}): "
                f"{computed_acres} acres at ({c_lat}, {c_lon})"
            )

        session.commit()
    return updated_count


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/load_plots.py <path_to_geojson>")
        sys.exit(1)
    target = Path(sys.argv[1])
    if not target.exists():
        print(f"File not found: {target}")
        sys.exit(1)
    count = load_plots_from_geojson(target)
    print(f"Done. Updated {count} plot(s).")
