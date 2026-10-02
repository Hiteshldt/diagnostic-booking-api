import pytest

from apps.bookings.models import Booking
from apps.centres.models import CentreTest, DiagnosticCentre, DiagnosticTest

from .conftest import future

# transaction=True: real commits, so the "invalidate the cache after commit" hook runs.
pytestmark = pytest.mark.django_db(transaction=True)


def test_anyone_can_list_centres_with_tests_and_prices(api, offering):
    response = api.get("/centres/")

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    centre = body["results"][0]
    assert centre["name"] == "EVE Diagnostics"
    assert centre["location"] == "Bengaluru"
    assert centre["tests"] == [
        {"id": offering.id, "test_id": offering.test_id, "name": "Complete Blood Count", "price": "500.00", "is_available": True}
    ]


def test_centre_list_is_paginated(api, db):
    DiagnosticCentre.objects.bulk_create(DiagnosticCentre(name=f"Centre {i:02}", location="Pune") for i in range(25))

    first = api.get("/centres/").json()
    second = api.get("/centres/?page=2").json()

    assert first["count"] == 25
    assert len(first["results"]) == 20
    assert first["next"] is not None
    assert len(second["results"]) == 5


def test_centres_can_be_searched_and_filtered_by_test(api, offering):
    other = DiagnosticCentre.objects.create(name="CityCare Labs", location="Mumbai")

    assert [c["id"] for c in api.get("/centres/?search=mumbai").json()["results"]] == [other.id]
    assert [c["id"] for c in api.get(f"/centres/?test={offering.test_id}").json()["results"]] == [offering.centre_id]
    assert api.get("/centres/?test=abc").status_code == 400


def test_unavailable_tests_are_hidden_from_the_centre_listing(api, offering):
    CentreTest.objects.filter(pk=offering.pk).update(is_available=False)

    assert api.get(f"/centres/{offering.centre_id}/").json()["tests"] == []


def test_only_admins_can_manage_centres(api, user_api, admin_api):
    payload = {"name": "New Centre", "location": "Chennai"}

    assert api.post("/centres/", payload).status_code == 401
    assert user_api.post("/centres/", payload).status_code == 403

    response = admin_api.post("/centres/", payload)
    assert response.status_code == 201
    assert response.json() == {"id": response.json()["id"], "name": "New Centre", "location": "Chennai", "tests": []}


def test_duplicate_centre_is_rejected(admin_api, offering):
    response = admin_api.post("/centres/", {"name": "EVE Diagnostics", "location": "Bengaluru"})

    assert response.status_code == 400


def test_admin_adds_a_test_to_a_centre_and_updates_its_price(admin_api, user_api, offering):
    test = admin_api.post("/tests/", {"name": "Lipid Profile"}).json()
    url = f"/centres/{offering.centre_id}/tests/"

    assert user_api.post(url, {"test_id": test["id"], "price": "700.00"}).status_code == 403

    created = admin_api.post(url, {"test_id": test["id"], "price": "700.00"})
    assert created.status_code == 201
    assert created.json()["price"] == "700.00"

    # offering the same test twice is a conflict, not a second row
    assert admin_api.post(url, {"test_id": test["id"], "price": "800.00"}).status_code == 409

    updated = admin_api.patch(f"{url}{created.json()['id']}/", {"price": "650.00"})
    assert updated.status_code == 200
    assert updated.json()["price"] == "650.00"

    assert len(admin_api.get(url).json()) == 2


@pytest.mark.parametrize("payload", [{"test_id": 999999, "price": "100.00"}, {"price": "100.00"}, {"test_id": None, "price": "-5"}])
def test_adding_a_test_validates_input(admin_api, offering, payload):
    if payload.get("test_id") is None and "test_id" in payload:
        payload["test_id"] = offering.test_id  # valid test, invalid price

    assert admin_api.post(f"/centres/{offering.centre_id}/tests/", payload).status_code == 400


def test_tests_of_an_unknown_centre_are_not_found(api, db):
    assert api.get("/centres/424242/tests/").status_code == 404
    assert api.get("/centres/424242/").status_code == 404


def test_centre_with_bookings_cannot_be_deleted(admin_api, user, offering):
    Booking.objects.create(user=user, centre_test=offering, appointment_at=future(), amount=offering.price)

    response = admin_api.delete(f"/centres/{offering.centre_id}/")

    assert response.status_code == 409
    assert DiagnosticCentre.objects.filter(pk=offering.centre_id).exists()


def test_centre_list_is_served_from_cache_and_refreshed_after_a_write(api, admin_api, offering, django_assert_num_queries):
    api.get("/centres/")  # fills the cache

    with django_assert_num_queries(0):
        assert api.get("/centres/").json()["count"] == 1

    admin_api.post("/centres/", {"name": "Brand New", "location": "Goa"})
    assert api.get("/centres/").json()["count"] == 2

    # a price change must show up too, not just new centres
    DiagnosticTest.objects.create(name="unrelated")  # catalogue writes also invalidate
    admin_api.patch(f"/centres/{offering.centre_id}/tests/{offering.id}/", {"price": "999.00"})
    centre = api.get(f"/centres/{offering.centre_id}/").json()
    assert centre["tests"][0]["price"] == "999.00"
