"""Strict JSON with a confidence for every field; nothing skips confirmation (pilot Part 5)."""

import copy
import json
from datetime import date

import pytest

from app.intake.draft_json import parse_rows
from app.intake.hosted import HostedVisionReader
from app.intake.prompt import RESPONSE_SCHEMA
from app.intake.reader import ReaderUnavailable
from app.intake.validate import LOW_CONFIDENCE_THRESHOLD

ROW = {
    "row": 1,
    "fields": {"phone": "੯੮੭੬੫੪੩੨੧੦", "name": None, "village": "Pind Kalan", "acres": "3.5 ਏਕੜ",
               "service_type": "ਸੁਪਰ seeder", "harvest_date": "18 ਅਕਤੂਬਰ", "note": None},
    "confidence": {"phone": 0.95, "name": 0.99, "village": 0.9, "acres": 0.55, "service_type": 0.9,
                   "harvest_date": 0.85},
}


def payload(**changes):
    row = copy.deepcopy(ROW)
    for path, value in changes.items():
        where, _, key = path.partition("__")
        if value is ...:
            row[where].pop(key)
        else:
            row[where][key] = value
    return json.dumps({"rows": [row]})


def test_a_good_answer_passes():
    assert parse_rows(payload())[0]["row"] == 1


@pytest.mark.parametrize(
    "changes, problem",
    [
        ({"confidence__name": ...}, "confidence for 'name'"),
        ({"confidence__acres": 1.5}, "confidence for 'acres'"),
        ({"confidence__phone": -0.1}, "confidence for 'phone'"),
        ({"confidence__phone": "0.9"}, "confidence for 'phone'"),
        ({"confidence__phone": True}, "confidence for 'phone'"),
        ({"fields__crop": "paddy"}, "unknown fields"),
        ({"fields__phone": ["9876543210"]}, "must be text, a number or null"),
    ],
)
def test_bad_answers_are_refused(changes, problem):
    with pytest.raises(ValueError, match=problem):
        parse_rows(payload(**changes))


def test_missing_confidence_object_and_bad_row_numbers():
    row = copy.deepcopy(ROW)
    row.pop("confidence")
    with pytest.raises(ValueError, match="'confidence' object is missing"):
        parse_rows(json.dumps({"rows": [row]}))
    r1, r2 = copy.deepcopy(ROW), copy.deepcopy(ROW)
    with pytest.raises(ValueError, match="used once"):
        parse_rows(json.dumps({"rows": [r1, r2]}))
    r1["row"] = 0
    with pytest.raises(ValueError, match="positive whole number"):
        parse_rows(json.dumps({"rows": [r1]}))


class S:
    allow_hosted_reader = True
    vision_provider = "gemini"
    vision_model = "model-x"
    reader_timeout_s = 5


def test_hosted_reader_retries_once_then_gives_up_on_missing_confidence():
    calls = []

    def client(image, media_type, prompt, timeout_s):
        calls.append(prompt)
        return payload(**{"confidence__village": ...})

    with pytest.raises(ReaderUnavailable, match="confidence for 'village'"):
        HostedVisionReader(settings=S(), client_callable=client, today_override=date(2026, 10, 25)).read(b"\xff\xd8\xffx")
    assert len(calls) == 2 and "confidence number from 0 to 1" in calls[1]


def test_low_confidence_and_failing_cells_reach_the_draft_for_highlighting():
    draft = HostedVisionReader(
        settings=S(), client_callable=lambda *a: payload(fields__phone="12345"), today_override=date(2026, 10, 25)
    ).read(b"\xff\xd8\xffx")
    r = draft.rows[0]
    assert r.confidence["acres"] == 0.55 < LOW_CONFIDENCE_THRESHOLD  # amber on screen
    assert r.confidence["phone"] <= 0.3  # failed validation -> capped -> red
    assert r.fields["acres"] == 3.5 and r.fields["service_type"] == "super_seeder"
    assert r.fields["harvest_date"] == "2026-10-18"


def test_gemini_schema_requires_every_confidence():
    conf = RESPONSE_SCHEMA["properties"]["rows"]["items"]["properties"]["confidence"]
    assert set(conf["required"]) == {"phone", "name", "village", "acres", "service_type", "harvest_date"}


def test_upload_never_creates_requests_only_confirm_does(client, auth_headers):
    from tests.fixtures.synthetic_photos import TINY_JPEG

    before = len(client.get("/api/requests", headers=auth_headers).json())
    up = client.post("/api/intake/register-photo", headers=auth_headers, files={"photo": ("p.jpg", TINY_JPEG, "image/jpeg")})
    assert up.status_code == 200 and len(up.json()["rows"]) == 6
    assert len(client.get("/api/requests", headers=auth_headers).json()) == before  # a draft is never a request
    # Confirming one row (and skipping the rest) creates exactly one request.
    first = up.json()["rows"][0]
    rows = [{"row": first["row"], "fields": first["fields"]}] + [
        {"row": r["row"], "fields": r["fields"], "skip": True} for r in up.json()["rows"][1:]
    ]
    res = client.post(f"/api/intake/{up.json()['intake_id']}/confirm", headers=auth_headers, json={"rows": rows})
    assert res.status_code == 201 and len(res.json()["created_request_ids"]) == 1
    assert len(client.get("/api/requests", headers=auth_headers).json()) == before + 1
