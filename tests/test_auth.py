import pytest

from .conftest import PASSWORD

pytestmark = pytest.mark.django_db


def test_signup_creates_user_and_returns_tokens(api):
    response = api.post("/auth/signup/", {"email": "New@Example.com", "password": PASSWORD, "full_name": "New User"})

    assert response.status_code == 201
    body = response.json()
    assert body["user"]["email"] == "new@example.com"  # normalised to lowercase
    assert body["access"] and body["refresh"]
    assert "password" not in body["user"]


def test_signup_rejects_duplicate_email_ignoring_case(api, user):
    response = api.post("/auth/signup/", {"email": "PATIENT@example.com", "password": PASSWORD})

    assert response.status_code == 400
    assert "email" in response.json()["error"]["details"]


@pytest.mark.parametrize(
    "payload, field",
    [
        ({"email": "not-an-email", "password": PASSWORD}, "email"),
        ({"email": "a@example.com", "password": "short"}, "password"),
        ({"email": "a@example.com", "password": "12345678901"}, "password"),  # all numeric
        ({"email": "a@example.com"}, "password"),
        ({"password": PASSWORD}, "email"),
    ],
)
def test_signup_validates_input(api, payload, field):
    response = api.post("/auth/signup/", payload)

    assert response.status_code == 400
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    assert field in error["details"]


def test_login_returns_tokens_that_work(api, user):
    response = api.post("/auth/login/", {"email": "Patient@example.com", "password": PASSWORD})
    assert response.status_code == 200

    api.credentials(HTTP_AUTHORIZATION=f"Bearer {response.json()['access']}")
    me = api.get("/auth/me/")
    assert me.status_code == 200
    assert me.json()["email"] == user.email


def test_login_with_wrong_password_is_rejected(api, user):
    response = api.post("/auth/login/", {"email": user.email, "password": "wrong-password"})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "no_active_account"


def test_refresh_issues_a_new_access_token(api, user):
    tokens = api.post("/auth/login/", {"email": user.email, "password": PASSWORD}).json()

    response = api.post("/auth/refresh/", {"refresh": tokens["refresh"]})

    assert response.status_code == 200
    assert response.json()["access"]


def test_protected_endpoint_requires_a_token(api):
    assert api.get("/auth/me/").status_code == 401
    assert api.get("/bookings/").status_code == 401


def test_invalid_token_is_rejected(api):
    api.credentials(HTTP_AUTHORIZATION="Bearer not-a-real-token")

    response = api.get("/auth/me/")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "token_not_valid"
