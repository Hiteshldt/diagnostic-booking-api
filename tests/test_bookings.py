from datetime import timedelta
from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.bookings.models import Booking, InvalidTransition
from apps.centres.models import CentreTest, DiagnosticTest

from .conftest import future

pytestmark = pytest.mark.django_db


def booking_payload(offering, when=None):
    return {
        "centre_id": offering.centre_id,
        "test_id": offering.test_id,
        "appointment_at": (when or future()).isoformat(),
    }


def test_user_books_a_test(user_api, user, offering):
    response = user_api.post("/bookings/", booking_payload(offering))

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "PENDING"
    assert body["amount"] == "500.00"
    assert body["user_id"] == user.id
    assert body["centre"] == {"id": offering.centre_id, "name": "EVE Diagnostics", "location": "Bengaluru"}
    assert body["test"] == {"id": offering.test_id, "name": "Complete Blood Count"}


def test_booking_requires_authentication(api, offering):
    assert api.post("/bookings/", booking_payload(offering)).status_code == 401
    assert Booking.objects.count() == 0


def test_booking_amount_is_fixed_at_booking_time(user_api, offering):
    booking_id = user_api.post("/bookings/", booking_payload(offering)).json()["id"]

    CentreTest.objects.filter(pk=offering.pk).update(price=Decimal("900.00"))

    assert user_api.get(f"/bookings/{booking_id}/").json()["amount"] == "500.00"


def test_client_cannot_choose_amount_status_or_owner(user_api, user, other_user, offering):
    payload = {**booking_payload(offering), "amount": "1.00", "status": "CONFIRMED", "user_id": other_user.id}

    body = user_api.post("/bookings/", payload).json()

    assert (body["amount"], body["status"], body["user_id"]) == ("500.00", "PENDING", user.id)


@pytest.mark.parametrize(
    "change, field",
    [
        ({"appointment_at": (timezone.now() - timedelta(hours=1)).isoformat()}, "appointment_at"),
        ({"appointment_at": "next tuesday"}, "appointment_at"),
        ({"appointment_at": None}, "appointment_at"),
        ({"centre_id": "abc"}, "centre_id"),
        ({"test_id": None}, "test_id"),
    ],
)
def test_booking_validates_input(user_api, offering, change, field):
    payload = {**booking_payload(offering), **change}
    payload = {key: value for key, value in payload.items() if value is not None}

    response = user_api.post("/bookings/", payload)

    assert response.status_code == 400
    assert field in response.json()["error"]["details"]


def test_cannot_book_a_test_the_centre_does_not_offer(user_api, offering):
    other_test = DiagnosticTest.objects.create(name="MRI Brain")

    not_offered = user_api.post("/bookings/", {**booking_payload(offering), "test_id": other_test.id})
    unknown_centre = user_api.post("/bookings/", {**booking_payload(offering), "centre_id": 424242})

    assert not_offered.status_code == 400
    assert unknown_centre.status_code == 400


def test_cannot_book_an_unavailable_test(user_api, offering):
    CentreTest.objects.filter(pk=offering.pk).update(is_available=False)

    assert user_api.post("/bookings/", booking_payload(offering)).status_code == 400


def test_duplicate_active_booking_is_a_conflict(user_api, offering):
    when = future()
    assert user_api.post("/bookings/", booking_payload(offering, when)).status_code == 201

    response = user_api.post("/bookings/", booking_payload(offering, when))

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"
    assert Booking.objects.count() == 1


def test_same_slot_can_be_rebooked_after_cancelling(user_api, offering):
    when = future()
    first = user_api.post("/bookings/", booking_payload(offering, when)).json()
    user_api.post(f"/bookings/{first['id']}/cancel/")

    assert user_api.post("/bookings/", booking_payload(offering, when)).status_code == 201


def test_database_rejects_a_duplicate_active_booking(user, offering):
    """The unique constraint is the real guarantee; the API check is only a nicer error."""
    when = future()
    Booking.objects.create(user=user, centre_test=offering, appointment_at=when, amount=offering.price)

    with pytest.raises(IntegrityError), transaction.atomic():
        Booking.objects.create(user=user, centre_test=offering, appointment_at=when, amount=offering.price)


def test_users_only_see_their_own_bookings(user_api, other_api, admin_api, booking):
    assert [b["id"] for b in user_api.get("/bookings/").json()["results"]] == [str(booking.id)]
    assert other_api.get("/bookings/").json()["results"] == []
    assert admin_api.get("/bookings/").json()["count"] == 1  # staff see everything


def test_bookings_can_be_filtered_by_status(user_api, booking):
    assert user_api.get("/bookings/?status=PENDING").json()["count"] == 1
    assert user_api.get("/bookings/?status=CONFIRMED").json()["count"] == 0
    assert user_api.get("/bookings/?status=nonsense").status_code == 400


def test_another_users_booking_looks_like_it_does_not_exist(other_api, booking):
    assert other_api.get(f"/bookings/{booking.id}/").status_code == 404
    assert other_api.post(f"/bookings/{booking.id}/cancel/").status_code == 404

    booking.refresh_from_db()
    assert booking.status == Booking.Status.PENDING


@pytest.mark.parametrize("bad_id", ["not-a-uuid", "12345", "00000000-0000-0000-0000-000000000000"])
def test_invalid_booking_id_is_not_found(user_api, bad_id):
    response = user_api.get(f"/bookings/{bad_id}/")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_user_cancels_their_booking(user_api, booking):
    response = user_api.post(f"/bookings/{booking.id}/cancel/")

    assert response.status_code == 200
    assert response.json()["status"] == "CANCELLED"


@pytest.mark.parametrize("final_status", [Booking.Status.CANCELLED, Booking.Status.FAILED])
def test_finished_booking_cannot_be_cancelled(user_api, booking, final_status):
    Booking.objects.filter(pk=booking.pk).update(status=final_status)

    response = user_api.post(f"/bookings/{booking.id}/cancel/")

    assert response.status_code == 409
    booking.refresh_from_db()
    assert booking.status == final_status


def test_bookings_cannot_be_edited_or_deleted_directly(user_api, booking):
    assert user_api.patch(f"/bookings/{booking.id}/", {"status": "CONFIRMED"}).status_code == 405
    assert user_api.delete(f"/bookings/{booking.id}/").status_code == 405


def test_state_machine_blocks_illegal_moves(booking):
    booking.transition_to(Booking.Status.FAILED)

    with pytest.raises(InvalidTransition):
        booking.transition_to(Booking.Status.CONFIRMED)
