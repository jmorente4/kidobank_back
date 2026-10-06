from io import BytesIO

import pytest
from PIL import Image

from app.core.security import create_access_token, get_password_hash
from app.models.user import User, UserRole
from app.models.user_avatar import UserAvatar
from app.services.avatar import MAX_UPLOAD_BYTES


def _headers(user):
    return {"Authorization": f"Bearer {create_access_token(subject=user.id)}"}


def _image(format="PNG", size=(1024, 768), color="red"):
    buffer = BytesIO()
    image = Image.new("RGB", size, color)
    exif = Image.Exif()
    exif[274] = 6
    exif[315] = "Private camera metadata"
    image.save(buffer, format=format, exif=exif)
    return buffer.getvalue()


def _child(db, parent, email="photo.child@kidobank.com"):
    user = User(
        nombre="Photo child",
        email=email,
        rol=UserRole.NINO,
        padre_id=parent.id,
        pin_hash=get_password_hash("1234"),
    )
    db.add(user)
    db.commit()
    return user


@pytest.mark.parametrize("format", ["JPEG", "PNG", "WEBP"])
def test_avatar_upload_is_optimized_oriented_and_private(client, padre_user, db, format):
    headers = _headers(padre_user)
    url = f"/api/v1/users/{padre_user.id}/avatar"
    upload = client.post(
        url, files={"file": ("camera.photo", _image(format), "application/octet-stream")},
        headers=headers,
    )
    assert upload.status_code == 200
    assert upload.json()["avatar_url"] == url
    photo = client.get(url, headers=headers)
    assert photo.status_code == 200
    assert photo.headers["content-type"] == "image/jpeg"
    assert photo.headers["cache-control"] == "private, no-store"
    with Image.open(BytesIO(photo.content)) as image:
        assert image.format == "JPEG"
        assert image.size == (384, 512)
        assert not image.getexif()
    assert db.get(UserAvatar, padre_user.id).imagen == photo.content
    assert client.get(url).status_code == 401
    assert client.post(url, files={"file": ("photo.png", _image())}).status_code == 401


def test_avatar_permissions_replacement_and_clear(client, padre_user, db):
    child = _child(db, padre_user)
    sibling = _child(db, padre_user, "photo.sibling@kidobank.com")
    outsider = User(
        nombre="Other parent", rol=UserRole.PADRE,
        email="photo.other@kidobank.com", pin_hash=get_password_hash("other123"),
    )
    db.add(outsider)
    db.commit()
    url = f"/api/v1/users/{child.id}/avatar"
    parent_headers = _headers(padre_user)
    child_headers = _headers(child)
    for user in (sibling, outsider):
        assert client.post(
            url, files={"file": ("photo.png", _image())}, headers=_headers(user)
        ).status_code == 403
        assert client.get(url, headers=_headers(user)).status_code == 403
    assert client.get(url, headers=parent_headers).status_code == 404
    assert client.post(
        url, files={"file": ("photo.png", _image())}, headers=parent_headers
    ).status_code == 200
    first = client.get(url, headers=child_headers).content
    assert client.post(
        url, files={"file": ("photo.png", _image(color="blue"))}, headers=child_headers
    ).status_code == 200
    assert client.get(url, headers=parent_headers).content != first
    assert db.query(UserAvatar).count() == 1
    assert client.patch(
        f"/api/v1/users/{child.id}", json={"nombre": "New name"}, headers=parent_headers
    ).status_code == 200
    assert client.get(url, headers=child_headers).status_code == 200
    assert client.patch(
        f"/api/v1/users/{child.id}", json={"avatar_url": None}, headers=child_headers
    ).status_code == 200
    assert client.get(url, headers=parent_headers).status_code == 404
    assert db.query(UserAvatar).count() == 0


@pytest.mark.parametrize(
    "data,expected",
    [(b"", 422), (b"not an image", 422), (b"x" * (MAX_UPLOAD_BYTES + 1), 413)],
    ids=["empty", "invalid", "too-large"],
)
def test_invalid_upload_does_not_replace_avatar(client, padre_user, data, expected):
    url = f"/api/v1/users/{padre_user.id}/avatar"
    headers = _headers(padre_user)
    assert client.post(
        url, files={"file": ("photo.png", _image())}, headers=headers
    ).status_code == 200
    original = client.get(url, headers=headers).content
    rejected = client.post(
        url, files={"file": ("photo.jpg", data, "image/jpeg")}, headers=headers
    )
    assert rejected.status_code == expected
    assert client.get(url, headers=headers).content == original


def test_avatar_pixel_limit(client, padre_user, monkeypatch):
    monkeypatch.setattr("app.services.avatar.MAX_IMAGE_PIXELS", 10)
    response = client.post(
        f"/api/v1/users/{padre_user.id}/avatar",
        files={"file": ("photo.png", _image(size=(4, 4)))},
        headers=_headers(padre_user),
    )
    assert response.status_code == 413


def test_avatar_removed_when_child_deleted(client, padre_user, db):
    child = _child(db, padre_user)
    headers = _headers(padre_user)
    assert client.post(
        f"/api/v1/users/{child.id}/avatar",
        files={"file": ("photo.png", _image())}, headers=headers,
    ).status_code == 200
    assert client.delete(f"/api/v1/users/{child.id}", headers=headers).status_code == 204
    assert db.query(UserAvatar).count() == 0


def test_external_url_replaces_stored_avatar(client, padre_user, db):
    headers = _headers(padre_user)
    url = f"/api/v1/users/{padre_user.id}/avatar"
    assert client.post(
        url, files={"file": ("photo.png", _image())}, headers=headers
    ).status_code == 200
    updated = client.patch(
        f"/api/v1/users/{padre_user.id}",
        json={"avatar_url": "https://example.com/avatar.png"}, headers=headers,
    )
    assert updated.status_code == 200
    assert updated.json()["avatar_url"] == "https://example.com/avatar.png"
    assert db.query(UserAvatar).count() == 0
