from io import BytesIO

from PIL import Image

from backend.integrations import waha_utils


def _png_bytes() -> bytes:
    image = Image.new("RGB", (512, 384), (35, 90, 160))
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


class _ImageResponse:
    status_code = 200
    headers = {"content-type": "image/png"}

    def __init__(self, content: bytes):
        self._content = content

    def iter_content(self, chunk_size: int = 8192):
        for index in range(0, len(self._content), chunk_size):
            yield self._content[index:index + chunk_size]


def test_persist_contact_profile_picture_as_webp(monkeypatch, tmp_path):
    image_bytes = _png_bytes()

    monkeypatch.setattr(waha_utils, "PROFILE_PICTURE_DIR", str(tmp_path))
    monkeypatch.setattr(
        waha_utils,
        "get_contact_profile_picture",
        lambda **kwargs: "https://example.test/profile.png",
    )
    monkeypatch.setattr(
        waha_utils.requests,
        "get",
        lambda *args, **kwargs: _ImageResponse(image_bytes),
    )

    photo_url = waha_utils.persist_contact_profile_picture_as_webp(
        waha_session_name="default",
        phone="5500000000007",
        company_id=42,
    )

    assert photo_url.startswith("/media/profile-pictures/company_42/")
    assert photo_url.endswith(".webp")

    saved_file = tmp_path / "company_42" / photo_url.rsplit("/", 1)[-1]
    assert saved_file.exists()

    with Image.open(saved_file) as saved_image:
        assert saved_image.format == "WEBP"
        assert max(saved_image.size) <= waha_utils.PROFILE_PICTURE_MAX_DIMENSION


def test_persist_contact_profile_picture_reuses_local_webp(monkeypatch):
    existing_photo = "/media/profile-pictures/company_42/contact_existing.webp"

    def fail_if_called(**kwargs):
        raise AssertionError("WAHA should not be called when local WebP already exists")

    monkeypatch.setattr(waha_utils, "get_contact_profile_picture", fail_if_called)

    photo_url = waha_utils.persist_contact_profile_picture_as_webp(
        waha_session_name="default",
        phone="5500000000007",
        company_id=42,
        existing_photo=existing_photo,
    )

    assert photo_url == existing_photo
