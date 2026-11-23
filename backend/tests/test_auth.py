from app.auth import hash_password, verify_password


def test_password_hash_verifies_only_original_password():
    encoded = hash_password("correct horse battery staple")
    assert encoded != "correct horse battery staple"
    assert verify_password("correct horse battery staple", encoded)
    assert not verify_password("incorrect password", encoded)


def test_password_hashes_are_salted():
    first = hash_password("correct horse battery staple")
    second = hash_password("correct horse battery staple")
    assert first != second
    assert verify_password("correct horse battery staple", first)
    assert verify_password("correct horse battery staple", second)


from types import SimpleNamespace

import jwt

from app.auth import create_access_token


def test_access_token_contains_expiry_and_issuer(monkeypatch):
    settings = SimpleNamespace(
        jwt_secret_key="s" * 48,
        jwt_issuer="vibestore-tests",
        jwt_access_token_minutes=15,
    )
    monkeypatch.setattr("app.auth.get_settings", lambda: settings)
    token = create_access_token("a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11")
    claims = jwt.decode(token, settings.jwt_secret_key, algorithms=["HS256"], issuer=settings.jwt_issuer)
    assert claims["sub"] == "a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11"
    assert claims["exp"] > claims["iat"]
