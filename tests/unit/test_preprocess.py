"""Image preprocessing before any reader (pilot Part 5)."""

import io

import pytest
from PIL import Image, ImageDraw

from app.intake import preprocess
from app.intake.preprocess import preprocess_for_reader, rotate_clockwise
from app.intake.reader import RegisterDraft


def page(size=(1500, 1000), bg=150, ink=110, orientation=None, arrow=True) -> bytes:
    """A dull grey synthetic 'page' with darker ink and a marker in the top-left corner."""
    img = Image.new("RGB", size, (bg, bg, bg))
    d = ImageDraw.Draw(img)
    for y in range(100, size[1] - 100, 80):
        d.line([(80, y), (size[0] - 80, y)], fill=(ink, ink, ink), width=4)
    if arrow:
        d.rectangle([0, 0, 60, 60], fill=(0, 0, 0))  # marks the true top-left
    buf = io.BytesIO()
    if orientation:
        exif = Image.Exif()
        exif[0x0112] = orientation
        img.save(buf, format="JPEG", exif=exif.tobytes(), quality=95)
    else:
        img.save(buf, format="JPEG", quality=95)
    return buf.getvalue()


def open_(b):
    return Image.open(io.BytesIO(b))


def test_contrast_is_stretched_and_page_is_greyscale():
    out, info = preprocess_for_reader(page(arrow=False))
    img = open_(out)
    assert img.mode == "L"
    lo, hi = img.getextrema()
    assert info.contrast_before[1] - info.contrast_before[0] < 60  # dull input
    assert hi - lo > 200  # stretched to nearly the full range


def test_big_photo_is_shrunk_to_2000_on_the_long_side():
    out, info = preprocess_for_reader(page(size=(4000, 3000)))
    assert open_(out).size == (2000, 1500) and info.resized


def test_small_scan_is_enlarged_to_1000():
    out, info = preprocess_for_reader(page(size=(600, 400)))
    assert open_(out).size == (1000, 667) and info.resized


def test_normal_size_is_kept_and_tiny_images_are_left_alone():
    _, info = preprocess_for_reader(page(size=(1500, 1000)))
    assert info.size == (1500, 1000) and not info.resized
    tiny = io.BytesIO()
    Image.new("L", (1, 1), 128).save(tiny, format="JPEG")
    _, info = preprocess_for_reader(tiny.getvalue())
    assert info.size == (1, 1)


def test_exif_rotation_is_applied():
    # Orientation 6: stored landscape, shown rotated 90 degrees clockwise (portrait).
    out, _ = preprocess_for_reader(page(size=(1500, 1000), orientation=6))
    assert open_(out).size == (1000, 1500)


@pytest.mark.parametrize("deg,corner", [(90, (1, 0)), (180, (1, 1)), (270, (0, 1))])
def test_manual_rotation_moves_the_marker(deg, corner):
    turned = open_(rotate_clockwise(page(size=(800, 600)), deg)).convert("L")
    w, h = turned.size
    x = 20 if corner[0] == 0 else w - 20
    y = 20 if corner[1] == 0 else h - 20
    assert turned.getpixel((x, y)) < 60  # the black marker is now in that corner


def test_bad_rotation_is_refused():
    with pytest.raises(ValueError):
        rotate_clockwise(page(), 45)


class SpyReader:
    from app.intake.reader import ReaderInfo

    info = ReaderInfo(name="mock", kind="mock")

    def __init__(self):
        self.got = []

    def read(self, image, media_type="image/jpeg"):
        self.got.append(image)
        return RegisterDraft(rows=[], reader="mock", prompt_version="v2", latency_ms=1)


def test_every_reader_gets_the_preprocessed_copy_and_staff_see_the_upright_page(client, auth_headers, monkeypatch):
    import app.routes.intake as intake_route

    spy = SpyReader()
    monkeypatch.setattr(intake_route, "get_reader", lambda s=None: spy)
    r = client.post(
        "/api/intake/register-photo",
        headers=auth_headers,
        files={"photo": ("p.jpg", page(size=(4000, 3000)), "image/jpeg")},
        data={"rotate": "90"},
    )
    assert r.status_code == 200, r.text
    sent = open_(spy.got[0])
    assert sent.mode == "L" and sent.size == (1500, 2000)  # turned, then shrunk
    stored = open_(client.get(f"/api/intake/{r.json()['intake_id']}/image", headers=auth_headers).content)
    assert stored.mode == "RGB" and stored.size == (3000, 4000)  # colour kept, turned


def test_upload_refuses_a_bad_rotate_value(client, auth_headers):
    r = client.post(
        "/api/intake/register-photo",
        headers=auth_headers,
        files={"photo": ("p.jpg", page(), "image/jpeg")},
        data={"rotate": "45"},
    )
    assert r.status_code == 422 and r.json()["details"]["field"] == "rotate"


def test_limits_are_the_documented_ones():
    assert (preprocess.MIN_LONG_SIDE, preprocess.MAX_LONG_SIDE, preprocess.TOO_SMALL) == (1000, 2000, 400)
