# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""The do-not-contact list (design 5.9): erased emails and phones kept only as keyed hashes.

Entries are added by the erasure job (`add_entries`) and looked up by every path that could bring
the person back (`blocked_values`). A missing hash secret while entries exist raises
`DncSecretUnavailableError`; each entry point decides to fail closed (manual saves, `blocking.py`) or
soft (mail, WhatsApp, Facebook: `skip_blocked`, `report_secret_unavailable`).
"""

from contextlib import contextmanager

import frappe
from frappe import _
from frappe.utils import escape_html, nowdate, today

from crm.fcrm.doctype.crm_privacy_settings.crm_privacy_settings import (
	DNC_DOCTYPE,
	DncSecretUnavailableError,
	_stored_secret,
	get_dnc_secret,
)
from crm.privacy.error_log import log_privacy_error
from crm.privacy.identifiers import KINDS, hash_identifier
from crm.privacy.roles import get_compliance_users


class ErasedPersonBlockedError(frappe.ValidationError):
	"""The record would carry an email or phone of a person who asked to be erased."""


class PrivacySettingsIncompleteError(frappe.ValidationError):
	"""The block could not be checked because the hash secret is missing (RT-15)."""


# What an automatic path (WhatsApp, Facebook sync) catches around a lead insert.
BLOCKING_ERRORS = (ErasedPersonBlockedError, PrivacySettingsIncompleteError)


def has_entries() -> bool:
	"""Whether the list holds anything. When it is empty no hash is needed, so a site that never erased
	anyone never reads or creates the secret on a save."""
	return bool(frappe.db.table_exists(DNC_DOCTYPE) and frappe.get_all(DNC_DOCTYPE, limit=1, pluck="name"))


def secret_available() -> bool:
	"""False only when entries exist but the key is gone (a restore with another `encryption_key`)."""
	return bool(_stored_secret()) or not has_entries()


def _kind(kind: str) -> str:
	kind = (kind or "").lower()
	if kind not in KINDS:
		raise ValueError(f"Unknown identifier kind: {kind!r}")
	return kind


def _hash(kind: str, value, secret: str) -> str | None:
	"""The hash of `value`, or None when there is nothing to hash (empty, or a phone without digits)."""
	try:
		return hash_identifier(kind, str(value or ""), secret)
	except ValueError:
		return None


def blocked_values(values) -> list[tuple[str, str]]:
	"""The `(kind, value)` pairs of `values` that are on the list: one indexed lookup for all of them.
	Raises DncSecretUnavailableError when entries exist and the secret does not."""
	pairs = [(_kind(kind), value) for kind, value in values if value and str(value).strip()]
	if not pairs or not has_entries():
		return []
	secret = get_dnc_secret()
	by_hash: dict[str, list] = {}
	for kind, value in pairs:
		if digest := _hash(kind, value, secret):
			by_hash.setdefault(digest, []).append((kind, value))
	if not by_hash:
		return []
	rows = frappe.get_all(DNC_DOCTYPE, {"identifier_hash": ["in", list(by_hash)]}, pluck="identifier_hash")
	found = set(rows)
	return [pair for digest, group in by_hash.items() if digest in found for pair in group]


def is_blocked(kind: str, value) -> bool:
	return bool(blocked_values([(kind, value)]))


def _listed(digest: str) -> bool:
	return bool(frappe.db.exists(DNC_DOCTYPE, digest))


def digest_of(kind: str, value) -> str | None:
	"""The stored hash of an identifier (None when there is nothing to hash). Needs the secret."""
	return _hash(_kind(kind), value, get_dnc_secret())


def add_entries(identifiers) -> int:
	"""Add `(kind, value)` pairs (kind `email`/`phone`, any case) to the list, skipping ones already
	there and empty ones. Returns how many were added. Only the hash is stored, and it is also the row's name,
	so two jobs adding the same identifier at once meet on the primary key and the second insert is ignored
	instead of failing the erasure. The first call on a site creates the secret (under a lock). Runs inside the
	caller's transaction."""
	pairs = [(_kind(kind), value) for kind, value in identifiers]
	secret = get_dnc_secret()
	added = 0
	for kind, value in pairs:
		digest = _hash(kind, value, secret)
		if not digest or _listed(digest):
			continue
		frappe.get_doc(
			{
				"doctype": DNC_DOCTYPE,
				"kind": kind.capitalize(),
				"identifier_hash": digest,
				"created_on": nowdate(),
			}
		).insert(ignore_permissions=True, ignore_if_duplicate=True)
		added += 1
	return added


def notify_compliance(text: str, link_doctype=None, link_name=None, *, once_a_day: bool = False) -> int:
	"""A CRM notification plus an email to every Compliance user. `text` must hold no personal data. With
	`once_a_day`, a user who already got the same text today is skipped. Returns how many were told."""
	body = escape_html(text)
	sent = 0
	for user in get_compliance_users():
		if once_a_day and frappe.db.exists(
			"CRM Notification",
			{"type": "Compliance", "to_user": user, "notification_text": body, "creation": [">=", today()]},
		):
			continue
		frappe.get_doc(
			{
				"doctype": "CRM Notification",
				"type": "Compliance",
				"to_user": user,
				"reference_doctype": link_doctype,
				"reference_name": link_name,
				"message": body,
				"notification_text": body,
			}
		).insert(ignore_permissions=True)
		_send_email(user, body, link_doctype, link_name)
		sent += 1
	return sent


def _send_email(user: str, body: str, link_doctype, link_name) -> None:
	failed = None
	try:
		frappe.sendmail(
			recipients=[user],
			subject=_("Privacy: action needed"),
			message=body,
			reference_doctype=link_doctype,
			reference_name=link_name,
		)
	except Exception as error:  # a mail setup problem must not undo the notification
		failed = type(error).__name__
	if failed:
		log_privacy_error("Privacy notice email", failed)


def report_secret_unavailable(context: str) -> None:
	"""Log (title and exception class only, no traceback, no identifier: V1) and tell Compliance, at most
	once a day."""
	log_privacy_error(f"DNC secret unavailable: {context}", DncSecretUnavailableError.__name__)
	notify_compliance(
		_(
			"The do-not-contact secret is missing, so new leads and emails cannot be checked against erased "
			"people. Restore it from a backup in Privacy settings."
		),
		once_a_day=True,
	)


@contextmanager
def skip_blocked(context: str):
	"""For an automatic path that skips the record instead of failing: run the block, and if it raises one of
	BLOCKING_ERRORS drop every message queued inside it (a red dialog nobody earned), report a missing secret,
	and set `.skipped` on the yielded state (and `.secret_missing` when that was the reason, so the caller can
	keep the record for a retry). Other errors pass through."""
	state = frappe._dict(skipped=False, secret_missing=False)
	queued = len(frappe.local.message_log)
	incomplete = False
	try:
		yield state
	except BLOCKING_ERRORS as error:
		del frappe.local.message_log[queued:]
		state.skipped = True
		incomplete = state.secret_missing = isinstance(error, PrivacySettingsIncompleteError)
	if incomplete:  # after the except block, so the Error Log keeps the class it is about
		report_secret_unavailable(context)
