import uuid

import pytest
from django.db import OperationalError

from apps.bookings.models import Booking
from apps.payments import services
from apps.payments.models import Payment, WebhookEvent

from .conftest import send_webhook

pytestmark = pytest.mark.django_db


def event(payment, status="SUCCESS", event_id="evt_1", **extra):
    return {"event_id": event_id, "payment_id": str(payment.id), "status": status, **extra}


def state(payment):
    payment.refresh_from_db()
    payment.booking.refresh_from_db()
    return payment.status, payment.booking.status


def test_success_event_settles_payment_and_confirms_booking(api, pending_payment):
    response = send_webhook(api, event(pending_payment))

    assert response.status_code == 200
    assert response.json() == {"event_id": "evt_1", "status": "PROCESSED", "duplicate": False}
    assert state(pending_payment) == ("SUCCESS", "CONFIRMED")


def test_failed_event_fails_payment_and_booking(api, pending_payment):
    send_webhook(api, event(pending_payment, "FAILED", failure_reason="Card declined"))

    assert state(pending_payment) == ("FAILED", "FAILED")
    assert pending_payment.failure_reason == "Card declined"


def test_webhook_needs_no_jwt_but_does_need_a_signature(api, pending_payment):
    unsigned = api.post("/payments/webhook/", event(pending_payment), format="json")
    wrong = send_webhook(api, event(pending_payment), signature_value="deadbeef")

    assert unsigned.status_code == 401
    assert wrong.status_code == 401
    assert wrong.json()["error"]["code"] == "invalid_signature"
    assert state(pending_payment) == ("PENDING", "PENDING")
    assert WebhookEvent.objects.count() == 0


def test_same_event_delivered_repeatedly_is_applied_once(api, pending_payment):
    """The core idempotency guarantee."""
    first = send_webhook(api, event(pending_payment))
    updated_at = Payment.objects.get(pk=pending_payment.pk).updated_at

    repeats = [send_webhook(api, event(pending_payment)) for _ in range(5)]

    assert first.json()["duplicate"] is False
    assert all(r.status_code == 200 and r.json()["duplicate"] is True for r in repeats)
    assert WebhookEvent.objects.count() == 1
    assert Payment.objects.count() == 1
    assert Booking.objects.count() == 1
    assert state(pending_payment) == ("SUCCESS", "CONFIRMED")
    assert Payment.objects.get(pk=pending_payment.pk).updated_at == updated_at  # row untouched


def test_replayed_event_id_with_a_different_status_changes_nothing(api, pending_payment):
    send_webhook(api, event(pending_payment, "SUCCESS"))

    replay = send_webhook(api, event(pending_payment, "FAILED"))

    assert replay.json()["duplicate"] is True
    assert state(pending_payment) == ("SUCCESS", "CONFIRMED")


def test_new_event_cannot_overturn_a_settled_payment(api, pending_payment):
    send_webhook(api, event(pending_payment, "SUCCESS", "evt_1"))

    late = send_webhook(api, event(pending_payment, "FAILED", "evt_2"))
    same = send_webhook(api, event(pending_payment, "SUCCESS", "evt_3"))

    assert late.status_code == 200 and late.json()["status"] == "IGNORED"
    assert same.status_code == 200 and same.json()["status"] == "IGNORED"
    assert state(pending_payment) == ("SUCCESS", "CONFIRMED")
    assert WebhookEvent.objects.count() == 3  # every event is kept for auditing


def test_event_for_a_payment_settled_by_the_api_is_ignored(api, user_api, booking):
    payment_id = user_api.post("/payments/", {"booking_id": str(booking.id), "simulate": "failed"}).json()["id"]
    payment = Payment.objects.get(pk=payment_id)

    response = send_webhook(api, event(payment, "SUCCESS"))

    assert response.json()["status"] == "IGNORED"
    assert state(payment) == ("FAILED", "FAILED")


def test_success_after_user_cancelled_does_not_revive_the_booking(api, user_api, pending_payment):
    user_api.post(f"/bookings/{pending_payment.booking_id}/cancel/")

    response = send_webhook(api, event(pending_payment, "SUCCESS"))

    assert response.status_code == 200
    assert state(pending_payment) == ("SUCCESS", "CANCELLED")


def test_event_for_unknown_payment_is_not_found_and_can_be_redelivered(api, booking):
    payment_id = uuid.uuid4()
    payload = {"event_id": "evt_early", "payment_id": str(payment_id), "status": "SUCCESS"}

    assert send_webhook(api, payload).status_code == 404
    assert send_webhook(api, payload).status_code == 404
    assert WebhookEvent.objects.get().status == WebhookEvent.Status.FAILED

    # the payment shows up later; the provider's retry of the same event now applies
    payment = Payment.objects.create(id=payment_id, booking=booking, amount=booking.amount)
    assert send_webhook(api, payload).status_code == 200
    assert state(payment) == ("SUCCESS", "CONFIRMED")
    assert WebhookEvent.objects.count() == 1


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"event_id": "evt_1", "status": "SUCCESS"},
        {"event_id": "evt_1", "payment_id": "not-a-uuid", "status": "SUCCESS"},
        {"event_id": "evt_1", "payment_id": str(uuid.uuid4()), "status": "REFUNDED"},
        {"event_id": "", "payment_id": str(uuid.uuid4()), "status": "SUCCESS"},
    ],
)
def test_invalid_payload_is_rejected(api, payload):
    response = send_webhook(api, payload)

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "validation_error"
    assert WebhookEvent.objects.count() == 0


def test_malformed_json_is_rejected(api):
    from apps.payments import signature

    body = "{not json"
    response = api.post(
        "/payments/webhook/", data=body, content_type="application/json",
        HTTP_X_WEBHOOK_SIGNATURE=signature.sign(body.encode()),
    )

    assert response.status_code == 400


def test_transient_database_error_stores_the_event_and_queues_a_retry(api, pending_payment, monkeypatch):
    queued = []
    monkeypatch.setattr(services, "process_event", lambda pk: (_ for _ in ()).throw(OperationalError("deadlock")))
    monkeypatch.setattr("apps.payments.views.process_webhook_event.delay", queued.append)

    response = send_webhook(api, event(pending_payment))

    stored = WebhookEvent.objects.get()
    assert response.status_code == 202
    assert stored.status == WebhookEvent.Status.RECEIVED
    assert queued == [stored.pk]


def test_processing_an_event_twice_is_harmless(pending_payment):
    stored, created = services.receive_event(event_id="evt_1", payload=event(pending_payment))
    again, created_again = services.receive_event(event_id="evt_1", payload=event(pending_payment))

    services.process_event(stored.pk)
    services.process_event(stored.pk)

    assert (created, created_again) == (True, False)
    assert again.pk == stored.pk
    assert state(pending_payment) == ("SUCCESS", "CONFIRMED")
