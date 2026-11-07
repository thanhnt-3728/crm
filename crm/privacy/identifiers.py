# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Identifier normalization and keyed hashing for the do-not-contact list (design 5.9).

Pure: no DB. The secret is passed in by the caller, never read here.
"""

import hashlib
import hmac
import re

import frappe
from frappe import _

from crm.utils import normalize_phone

KINDS = ("email", "phone")
MIN_PHONE_DIGITS = 7
# National-format numbers are read as US numbers (CCPA is a US law). Without this the hash would
# depend on the site country in System Settings, and changing it would silently drop every block.
PHONE_REGION = "US"
# One "@", no whitespace, and a dot inside the domain. Deliberately loose: the goal is to catch
# typos before a request is logged, not to prove deliverability.
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s.]+(\.[^@\s.]+)+$")


def normalize_email(value: str | None) -> str:
	return (value or "").strip().lower()


def _phone(value: str | None) -> str:
	"""A leading `00` is the international dialling prefix, so it reads as `+` (`001 415...` is `+1 415...`)."""
	value = (value or "").strip()
	return "+" + value[2:] if value.startswith("00") else value


def normalize_identifier(kind: str, value: str | None) -> str:
	"""Canonical form of an email (trimmed, lowercased) or phone (E.164). Raises ValueError for any other kind."""
	if kind == "email":
		return normalize_email(value)
	if kind == "phone":
		return normalize_phone(_phone(value), region=PHONE_REGION)
	raise ValueError(f"Unknown identifier kind: {kind!r}")


def hash_identifier(kind: str, value: str | None, secret: str) -> str:
	"""HMAC-SHA256 hex of `"<kind>:<normalized value>"`. The kind prefix keeps an email and a phone
	with the same text apart. Raises ValueError on an empty value or secret, so a block can never be
	written against nothing or against an unkeyed hash."""
	if not secret:
		raise ValueError("A hash secret is required")
	normalized = normalize_identifier(kind, value)
	if not normalized:
		raise ValueError("Cannot hash an empty identifier")
	return hmac.new(secret.encode(), f"{kind}:{normalized}".encode(), hashlib.sha256).hexdigest()


def validate_identifier(kind: str, value: str | None) -> None:
	"""Return None when `value` is usable as an identifier of `kind`, else raise frappe.ValidationError
	with a message fit to show the user. Callers that want a boolean can catch ValidationError."""
	if kind == "email":
		if not EMAIL_PATTERN.match(normalize_email(value)):
			frappe.throw(_("{0} is not a valid email address").format(value or _("An empty value")))
	elif kind == "phone":
		digits = re.sub(r"\D", "", normalize_phone(_phone(value), region=PHONE_REGION))
		if len(digits) < MIN_PHONE_DIGITS:
			frappe.throw(
				_("{0} is not a valid phone number (at least {1} digits)").format(
					value or _("An empty value"), MIN_PHONE_DIGITS
				)
			)
	else:
		frappe.throw(_("Unknown identifier kind: {0}").format(kind))
