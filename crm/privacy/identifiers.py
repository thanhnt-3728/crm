"""Identifier normalization and keyed hashing for privacy (erasure) requests."""

import hashlib
import hmac
import secrets
from typing import Literal

import frappe
from frappe.utils.password import get_decrypted_password, set_encrypted_password

from crm.utils import normalize_phone

SETTINGS = "CRM Privacy Settings"

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


def _read_secret() -> str | None:
	return get_decrypted_password(SETTINGS, SETTINGS, "identifier_secret", raise_exception=False)


def ensure_secret() -> str:
	"""Create the identifier-hash key once and return it.

	The key lives only in `__Auth` (encrypted), deliberately with no docfield on the
	settings doctype, so saving the settings can never overwrite or clear it. Called
	from install/migrate so the key exists before any request needs it.
	"""
	secret = _read_secret()
	if secret:
		return secret
	secret = secrets.token_hex(32)
	set_encrypted_password(SETTINGS, SETTINGS, secret, "identifier_secret")
	return secret


def get_secret() -> str:
	"""The HMAC key for identifier hashes. Falls back to creating it if migrate did not."""
	return _read_secret() or ensure_secret()


def personal_fields() -> dict[str, set[str]]:
	"""Doctype -> fieldnames an erasure scrubs, as configured in CRM Privacy Settings."""
	rows = frappe.get_all(
		"CRM Personal Field",
		filters={"parent": SETTINGS, "parenttype": SETTINGS, "parentfield": "personal_fields"},
		fields=["document_type", "fieldname"],
		parent_doctype=SETTINGS,
	)
	result: dict[str, set[str]] = {}
	for row in rows:
		result.setdefault(row.document_type, set()).add(row.fieldname)
	return result


def _identifier_hash(kind: str, value: str | None) -> str | None:
	normalized = normalize_identifier(kind, value)
	if not normalized:
		return None
	return hash_identifier(kind, normalized, get_secret())


def is_blocked(kind: Literal["Email", "Phone"], value: str | None) -> bool:
	identifier_hash = _identifier_hash(kind, value)
	if not identifier_hash:
		return False
	return bool(frappe.db.exists("CRM Do Not Contact", {"identifier_hash": identifier_hash}))


def blocking_request(kind: Literal["Email", "Phone"], value: str | None) -> str | None:
	"""The request recorded on the do-not-contact entry that blocks this value, if any."""
	identifier_hash = _identifier_hash(kind, value)
	if not identifier_hash:
		return None
	return frappe.db.get_value("CRM Do Not Contact", {"identifier_hash": identifier_hash}, "request")


def add_do_not_contact(kind: Literal["Email", "Phone"], value: str | None, request: str) -> None:
	"""Record the identifier's hash (never the identifier) as do-not-contact. Idempotent."""
	identifier_hash = _identifier_hash(kind, value)
	if not identifier_hash:
		return
	if frappe.db.exists("CRM Do Not Contact", {"identifier_hash": identifier_hash}):
		return
	try:
		frappe.get_doc(
			{
				"doctype": "CRM Do Not Contact",
				"identifier_hash": identifier_hash,
				"kind": kind,
				"request": request,
			}
		).insert(ignore_permissions=True)
	except frappe.DuplicateEntryError:
		pass


def compliance_users() -> list[str]:
	"""Enabled users holding the Compliance role (Administrator and Guest excluded)."""
	holders = frappe.get_all(
		"Has Role",
		filters={
			"role": "Compliance",
			"parenttype": "User",
			"parent": ["not in", ["Administrator", "Guest"]],
		},
		pluck="parent",
		ignore_permissions=True,
	)
	if not holders:
		return []
	return frappe.get_all(
		"User",
		filters={"name": ["in", holders], "enabled": 1},
		pluck="name",
	)
