"""Identifier normalization and keyed hashing for privacy (erasure) requests."""

import hashlib
import hmac
from typing import Literal

from crm.utils import normalize_phone

# Fixed so stored hashes do not change if System Settings' country does.
PHONE_REGION = "US"


def normalize_email(value: str | None) -> str:
	return (value or "").strip().lower()


def normalize_identifier(kind: Literal["Email", "Phone"], value: str | None) -> str:
	if kind == "Phone":
		return normalize_phone(value, region=PHONE_REGION)
	return normalize_email(value)


def hash_identifier(kind: str, normalized: str, secret: str) -> str:
	"""Hex HMAC-SHA256 of `kind:normalized`, keyed with `secret`."""
	msg = f"{kind}:{normalized}"
	return hmac.new(secret.encode(), msg.encode(), hashlib.sha256).hexdigest()
