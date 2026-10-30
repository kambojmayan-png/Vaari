"""API routes for managing plots (Contract Section 11 & Step 07)."""

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app import clock
from app.auth import Principal, require_operator
from app.db import get_db
from app.enums import to_x100
from app.errors import VaariError
from app.evidence.area import acres_of_polygon, centroid_of_polygon
from app.models import Farmer, Plot, Village
from app.routes.common import serialize_plot
from app.schemas import PlotIn, PlotOut, validate_acres_val

router = APIRouter(prefix="/plots", tags=["plots"])


@router.post("", response_model=PlotOut, status_code=status.HTTP_201_CREATED)
def create_plot(
    payload: PlotIn,
    session: Session = Depends(get_db),
    _principal: Principal = Depends(require_operator),
):
    farmer = session.query(Farmer).filter_by(phone=payload.farmer_phone).first()
    if farmer is None:
        farmer = Farmer(
            phone=payload.farmer_phone,
            name=None,
            language="pa",
            consent_service=True,
            consent_evidence=True,
            consent_share=True,
            consent_at=clock.now_utc(),
            consent_simulated=True,
        )
        session.add(farmer)
        session.flush()

    village = session.query(Village).filter_by(name=payload.village).first()
    village_id = village.id if village else None

    warning_msg: str | None = None

    if payload.geojson is not None:
        try:
            poly_acres = acres_of_polygon(payload.geojson)
            c_lat, c_lon = centroid_of_polygon(payload.geojson)
            validate_acres_val(poly_acres)
        except Exception as exc:
            raise VaariError(
                error_code="VALIDATION_ERROR",
                message=f"Invalid plot polygon: {exc}",
                http_status=422,
                details={"field": "geojson"},
            ) from exc

        if payload.acres is not None and poly_acres > 0:
            diff_ratio = abs(payload.acres - poly_acres) / poly_acres
            if diff_ratio > 0.10:
                warning_msg = (
                    f"Stated acres ({payload.acres}) differed from polygon area "
                    f"({poly_acres} acres) by more than 10%; using polygon value."
                )

        acres_x100 = to_x100(poly_acres)
        location_source = "polygon"
        pin_lat = payload.pin_lat
        pin_lon = payload.pin_lon
        centroid_lat, centroid_lon = c_lat, c_lon
    else:
        if payload.acres is None:
            raise VaariError(
                error_code="VALIDATION_ERROR",
                message="Acres is required when no polygon is provided.",
                http_status=422,
                details={"field": "acres"},
            )
        acres_x100 = to_x100(payload.acres)
        if payload.pin_lat is not None and payload.pin_lon is not None:
            location_source = "pin"
            pin_lat, pin_lon = payload.pin_lat, payload.pin_lon
        elif village is not None:
            location_source = "village"
            pin_lat, pin_lon = village.lat, village.lon
        else:
            location_source = "none"
            pin_lat, pin_lon = None, None
        centroid_lat, centroid_lon = pin_lat, pin_lon

    plot = Plot(
        farmer_id=farmer.id,
        village_name=payload.village,
        village_id=village_id,
        pin_lat=pin_lat,
        pin_lon=pin_lon,
        geojson=payload.geojson,
        acres_x100=acres_x100,
        centroid_lat=centroid_lat,
        centroid_lon=centroid_lon,
        location_source=location_source,
    )
    session.add(plot)
    session.commit()

    return serialize_plot(plot, warning=warning_msg)


@router.get("", response_model=list[PlotOut])
def list_plots(
    session: Session = Depends(get_db),
    _principal: Principal = Depends(require_operator),
):
    plots = session.query(Plot).order_by(Plot.id.asc()).all()
    return [serialize_plot(p) for p in plots]


@router.get("/{id}", response_model=PlotOut)
def get_plot(
    id: int,
    session: Session = Depends(get_db),
    _principal: Principal = Depends(require_operator),
):
    plot = session.query(Plot).filter_by(id=id).first()
    if plot is None:
        raise VaariError("NOT_FOUND", "Plot not found.", 404)
    return serialize_plot(plot)
