#!/usr/bin/env python
"""
Pretend to be the payment provider: send a signed webhook to the API.

    python scripts/send_webhook.py <payment_id> SUCCESS
    python scripts/send_webhook.py <payment_id> FAILED --event-id evt_42

Run it twice with the same --event-id to see idempotency in action.
Uses only the standard library.
"""

import argparse
import hashlib
import hmac
import json
import os
import urllib.error
import urllib.request
import uuid

parser = argparse.ArgumentParser()
parser.add_argument("payment_id")
parser.add_argument("status", choices=["SUCCESS", "FAILED"])
parser.add_argument("--event-id", default=f"evt_{uuid.uuid4().hex[:12]}")
parser.add_argument("--url", default="http://localhost:8000/payments/webhook/")
parser.add_argument("--secret", default=os.environ.get("WEBHOOK_SECRET", "dev-webhook-secret"))
args = parser.parse_args()

body = json.dumps({"event_id": args.event_id, "payment_id": args.payment_id, "status": args.status}).encode()
signature = hmac.new(args.secret.encode(), body, hashlib.sha256).hexdigest()
request = urllib.request.Request(
    args.url, data=body, headers={"Content-Type": "application/json", "X-Webhook-Signature": signature}
)

try:
    with urllib.request.urlopen(request) as response:
        print(response.status, response.read().decode())
except urllib.error.HTTPError as error:
    print(error.code, error.read().decode())
