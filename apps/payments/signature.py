"""
Webhook authenticity.

The provider and this service share a secret. The provider signs the exact
request body with HMAC-SHA256 and sends the result in the X-Webhook-Signature
header; we recompute it and compare. Without the secret, nobody can forge a
"payment succeeded" call.
"""

import hashlib
import hmac

from django.conf import settings

HEADER = "X-Webhook-Signature"


def sign(body: bytes) -> str:
    return hmac.new(settings.WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()


def is_valid(body: bytes, signature: str) -> bool:
    # compare_digest takes the same time whether or not the strings match,
    # so the response time leaks nothing about the correct signature.
    return hmac.compare_digest(sign(body), signature or "")
