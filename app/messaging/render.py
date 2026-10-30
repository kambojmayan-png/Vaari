"""Slot message rendering (Punjabi and English) and wa.me / tel links."""

import json
from pathlib import Path
from urllib.parse import quote

from app import clock
from app.enums import from_x100
from app.models import Centre, Farmer, Machine, Plot, Request, Slot

TEMPLATES_PATH = Path(__file__).parent / "templates.json"


def load_templates() -> dict[str, str]:
    return json.loads(TEMPLATES_PATH.read_text(encoding="utf-8"))


def render_slot_message(
    slot: Slot,
    req: Request,
    farmer: Farmer,
    plot: Plot,
    machine: Machine,
    centre: Centre,
) -> dict[str, str | int]:
    """Render slot messages in Punjabi and English with wa.me and tel: links."""
    templates = load_templates()

    acres_val = from_x100(req.acres_x100)
    acres_str = f"{acres_val:g}"

    context_pa = {
        "village": plot.village_name,
        "acres": acres_str,
        "machine": machine.name,
        "date": clock.fmt_pa(slot.service_date),
        "code": slot.service_code,
        "centre_phone": centre.phone,
        "centre_name": centre.name,
    }

    context_en = {
        "village": plot.village_name,
        "acres": acres_str,
        "machine": machine.name,
        "date": clock.fmt_en(slot.service_date),
        "code": slot.service_code,
        "centre_phone": centre.phone,
        "centre_name": centre.name,
    }

    body_pa = templates["pa"].format(**context_pa)
    body_en = templates["en"].format(**context_en)

    encoded_text = quote(body_pa)
    wa_link = f"https://wa.me/91{farmer.phone}?text={encoded_text}"
    tel_link = f"tel:+91{farmer.phone}"

    return {
        "slot_id": slot.id,
        "language": farmer.language or "pa",
        "body": body_pa,
        "body_en": body_en,
        "wa_link": wa_link,
        "tel_link": tel_link,
        "service_code": slot.service_code,
    }
