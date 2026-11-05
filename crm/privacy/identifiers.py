import hashlib
import hmac
import re
from email.utils import getaddresses

import phonenumbers
from phonenumbers import NumberParseException

# `frappe` and `crm.utils` are imported inside the functions that need them, so the
# pure text helpers (normalize_email, extract_emails, text_contains_email) work
# without a site.


def normalize_email(v: str | None) -> str:
	"""Canonical form of an email address: stripped and lowercased, "" when empty."""
	return (v or "").strip().lower()


def normalize(kind: str, v: str | None) -> str:
	"""Canonical form of an identifier. `kind` is "Email" or "Phone"."""
	if kind == "Email":
		return normalize_email(v)
	if kind == "Phone":
		from crm.utils import normalize_phone

		return normalize_phone(v)
	raise ValueError(f"Unknown identifier kind: {kind}")


def scramble(kind: str, v: str | None) -> str:
	"""Keyed one-way hash (HMAC-SHA256 hex) of a normalized identifier, so the
	do-not-contact list never holds the identifier itself."""
	import frappe

	from crm.privacy import settings

	secret = settings().get_password("hash_secret")
	if not secret:
		frappe.throw("CRM Privacy Settings has no hash secret.")
	message = f"{kind}:{normalize(kind, v)}".encode()
	return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def add_do_not_contact(kind: str, v: str | None) -> None:
	"""Record an identifier as do-not-contact. Idempotent; stores only the hash."""
	import frappe

	if not normalize(kind, v):
		return
	value_hash = scramble(kind, v)
	if frappe.db.exists("CRM Do Not Contact", {"value_hash": value_hash}):
		return
	try:
		frappe.get_doc({"doctype": "CRM Do Not Contact", "kind": kind, "value_hash": value_hash}).insert(
			ignore_permissions=True
		)
	except frappe.UniqueValidationError:
		# Lost a race with a concurrent insert of the same identifier.
		pass


def is_do_not_contact(kind: str, v: str | None) -> bool:
	import frappe

	if not normalize(kind, v):
		return False
	return bool(frappe.db.exists("CRM Do Not Contact", {"value_hash": scramble(kind, v)}))


def extract_emails(header: str | None) -> list[str]:
	"""Normalized addresses in a recipients string such as
	`"Marisol Vega" <Marisol.Vega@x.net>, bob@x.net`."""
	emails = []
	for _name, address in getaddresses([header or ""]):
		address = normalize_email(address)
		if address:
			emails.append(address)
	return emails


def text_contains_email(text: str | None, email: str | None) -> bool:
	"""Whether `text` contains the email address, ignoring case."""
	target = normalize_email(email)
	if not text or not target:
		return False
	return target in text.lower()


def text_contains_phone(text: str | None, phone: str | None) -> bool:
	"""Whether `text` contains the phone number in any formatting: non-digits are
	stripped from the text and the number's national-number digits looked up in it."""
	if not text or not phone:
		return False
	from crm.utils import normalize_phone

	normalized = normalize_phone(phone)
	if not normalized:
		return False
	try:
		digits = str(phonenumbers.parse(normalized, None).national_number)
	except NumberParseException:
		digits = re.sub(r"\D", "", normalized)
	if not digits:
		return False
	return digits in re.sub(r"\D", "", text)
