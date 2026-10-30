"""Gurmukhi digits and mixed Punjabi and English register entries (pilot Part 5)."""

from datetime import date

import pytest

from app.intake.normalize import (
    month_name_date,
    normalize_phone,
    normalize_service,
    parse_acres,
    to_ascii_digits,
)
from app.intake.validate import has_blocking_issues, validate_row

TODAY = date(2026, 10, 25)


def row(**fields):
    base = {"phone": "9000000101", "village": "Pind Kalan", "acres": "3", "service_type": "super_seeder", "harvest_date": None}
    base.update(fields)
    return base


# --- digits -------------------------------------------------------------------

def test_every_gurmukhi_digit_maps_to_its_ascii_digit():
    assert to_ascii_digits("੦੧੨੩੪੫੬੭੮੯") == "0123456789"
    assert to_ascii_digits("०१२३४५६७८९") == "0123456789"  # Devanagari too
    assert to_ascii_digits("ਪਿੰਡ ੧੨") == "ਪਿੰਡ 12"  # letters are left alone


# --- phone numbers -------------------------------------------------------------

@pytest.mark.parametrize(
    "raw",
    [
        "੯੮੭੬੫੪੩੨੧੦",  # all Gurmukhi
        "੯੮੭੬5 43210",  # Gurmukhi and ASCII mixed, with a space
        "੯੮੭੬੫-੪੩੨੧੦",  # Gurmukhi with a dash
        "+੯੧ ੯੮੭੬੫ ੪੩੨੧੦",  # country code in Gurmukhi
        "+91 98765 43210",
        "91-98765-43210",  # 12 digits without the plus
        "098765 43210",  # trunk zero
        "ਫ਼ੋਨ: ੯੮੭੬੫ ੪੩੨੧੦",  # Punjabi label
        "Mob. 98765-43210",  # English label
        "(98765) 43210।",  # brackets and a danda
    ],
)
def test_phone_forms_all_become_the_same_number(raw):
    assert normalize_phone(raw) == "9876543210"
    clean, issues = validate_row(row(phone=raw), TODAY)
    assert clean["phone"] == "9876543210" and issues == []


@pytest.mark.parametrize("raw", ["੯੮੭੬੫ ੪੩੨੧", "98765 43210 / 98111 22233", "੧੨੩੪੫੬੭੮੯੦", "98765O3210"])
def test_bad_phones_stay_flagged(raw):
    conf = {"phone": 0.95}
    _, issues = validate_row(row(phone=raw), TODAY, confidence=conf)
    assert any(i.startswith("phone:") for i in issues)
    assert conf["phone"] <= 0.3  # highlighted on the confirmation screen


# --- acres -------------------------------------------------------------------

@pytest.mark.parametrize(
    "raw, expected",
    [
        ("੩.੫", 3.5),
        ("੩.੫ ਏਕੜ", 3.5),
        ("3.5 acre", 3.5),
        ("3.5 Acres", 3.5),
        ("੪ ਕਿੱਲੇ", 4.0),
        ("4 kille", 4.0),
        ("4 killa", 4.0),
        ("੩½", 3.5),
        ("2 1/2 acre", 2.5),
        ("੨ ੧/੨ ਏਕੜ", 2.5),
        ("1/2", 0.5),
        (3.25, 3.25),
    ],
)
def test_acres_forms(raw, expected):
    clean, issues = validate_row(row(acres=raw), TODAY)
    assert clean["acres"] == expected, (raw, clean["acres"], issues)
    assert issues == []


def test_kanal_is_converted_with_a_warning_that_does_not_block():
    conf = {"acres": 0.9}
    clean, issues = validate_row(row(acres="੪ ਕਨਾਲ"), TODAY, confidence=conf)
    assert clean["acres"] == 0.5
    assert issues == ["acres: converted from 4 kanal (8 kanal = 1 acre), check the register"]
    assert conf["acres"] <= 0.3  # highlighted for a person to check
    assert not has_blocking_issues(issues)
    assert parse_acres("12 kanal") == ("1.5", "acres: converted from 12 kanal (8 kanal = 1 acre), check the register")


@pytest.mark.parametrize("raw", ["ਤਿੰਨ ਏਕੜ", "3 to 4", "3,5", "about 4", ""])
def test_unreadable_acres_are_flagged_not_guessed(raw):
    clean, issues = validate_row(row(acres=raw), TODAY)
    assert any(i.startswith("acres:") for i in issues), (raw, clean["acres"])
    assert has_blocking_issues(issues)


# --- service type -------------------------------------------------------------

@pytest.mark.parametrize(
    "raw, expected",
    [
        ("ਸੁਪਰ seeder", "super_seeder"),
        ("Super ਸੀਡਰ", "super_seeder"),
        ("ਸੁਪਰਸੀਡਰ", "super_seeder"),
        ("S.S.", "super_seeder"),
        ("ਹੈਪੀ seeder", "happy_seeder"),
        ("happy-seeder", "happy_seeder"),
        ("ਬੇਲਰ (baler)", "baler"),
        ("Mulcher ਮਲਚਰ", "mulcher"),
        ("ਸੁਪਰ ਸੀਡਰ", "super_seeder"),
    ],
)
def test_mixed_service_names(raw, expected):
    assert normalize_service(raw) == expected
    clean, issues = validate_row(row(service_type=raw), TODAY)
    assert clean["service_type"] == expected and issues == []


def test_unknown_service_stays_flagged():
    clean, issues = validate_row(row(service_type="ਟਰੈਕਟਰ"), TODAY)
    assert clean["service_type"] == "ਟਰੈਕਟਰ" and any(i.startswith("service_type:") for i in issues)


# --- dates ---------------------------------------------------------------------

@pytest.mark.parametrize(
    "raw, expected",
    [
        ("੧੮/੧੦", "2026-10-18"),
        ("੧੮-੧੦-੨੦੨੬", "2026-10-18"),
        ("18 ਅਕਤੂਬਰ", "2026-10-18"),
        ("੧੮ ਅਕਤੂਬਰ", "2026-10-18"),
        ("੧੮ ਅਕਤੂਬਰ ੨੦੨੬", "2026-10-18"),
        ("2 ਨਵੰਬਰ", "2026-11-02"),
        ("18 Oct", "2026-10-18"),
        ("Oct 18", "2026-10-18"),
        ("18-Oct-2026", "2026-10-18"),
        ("18 October", "2026-10-18"),
    ],
)
def test_dates_with_gurmukhi_digits_and_month_names(raw, expected):
    clean, issues = validate_row(row(harvest_date=raw), TODAY)
    assert clean["harvest_date"] == expected and issues == []


def test_month_name_parser_rejects_noise():
    assert month_name_date("ਕੱਲ੍ਹ") is None
    assert month_name_date("18 ਅਕਤੂਬਰ ਸ਼ਾਮ") is None
    clean, issues = validate_row(row(harvest_date="31 ਨਵੰਬਰ"), TODAY)
    assert issues == ["harvest_date: invalid calendar date"]


# --- names and villages ----------------------------------------------------------

def test_mixed_script_village_and_name_are_kept_as_written():
    clean, issues = validate_row(row(village="  ਪਿੰਡ Kalan ", name="Gurpreet ਸਿੰਘ"), TODAY)
    assert clean["village"] == "ਪਿੰਡ Kalan" and clean["name"] == "Gurpreet ਸਿੰਘ" and issues == []
