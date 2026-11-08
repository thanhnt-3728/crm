"""Placeholder text and identifier scrubbing for privacy (erasure) requests."""

import copy
import re
from collections.abc import Callable
from email.utils import getaddresses
from typing import Any

import phonenumbers

from crm.privacy.identifiers import PHONE_REGION, normalize_email, normalize_identifier

# A confirmed email matches only as a whole address: not glued to a preceding address
# character, and not continued by a longer name or domain (a@b.example.org, a@b.example-x).
_EMAIL_START = r"(?<![\w.+%-])"
_EMAIL_END = r"(?![\w-])(?!\.\w)"


# Seeded into CRM Privacy Settings (only while its table is empty).
DEFAULT_PERSONAL_FIELDS: dict[str, list[str]] = {
	"CRM Lead": [
		"salutation",
		"first_name",
		"middle_name",
		"last_name",
		"lead_name",
		"email",
		"mobile_no",
		"phone",
		"job_title",
		"image",
		"gender",
		"linkedin",
		"twitter",
		"facebook",
	],
	"CRM Deal": [
		"salutation",
		"first_name",
		"last_name",
		"lead_name",
		"email",
		"mobile_no",
		"phone",
		"job_title",
		"gender",
		"linkedin",
		"twitter",
		"facebook",
	],
	"Contact": [
		"salutation",
		"first_name",
		"middle_name",
		"last_name",
		"full_name",
		"email_id",
		"mobile_no",
		"phone",
		"designation",
		"image",
		"gender",
	],
	"Contact Email": ["email_id"],
	"Contact Phone": ["phone"],
	"CRM Contacts": ["full_name", "email", "mobile_no", "phone", "gender"],
}

# Name and identifier fields an erasure always scrubs, whatever the settings list says.
_ALWAYS_ERASED = frozenset(
	{
		"first_name",
		"middle_name",
		"last_name",
		"full_name",
		"lead_name",
		"email",
		"email_id",
		"mobile_no",
		"phone",
	}
)
REQUIRED_PERSONAL_FIELDS: dict[str, list[str]] = {
	document_type: [fieldname for fieldname in fieldnames if fieldname in _ALWAYS_ERASED]
	for document_type, fieldnames in DEFAULT_PERSONAL_FIELDS.items()
}

# Report, ownership and naming fields that may never be listed: dashboards count and sum
# leads and deals by these, and erasing them would change the numbers.
FORBIDDEN_PERSONAL_FIELDS = frozenset(
	{
		"name",
		"naming_series",
		"status",
		"source",
		"territory",
		"lead_owner",
		"deal_owner",
		"organization",
		"deal_value",
		"annual_revenue",
		"probability",
		"currency",
		"exchange_rate",
		"expected_closure_date",
		"closed_date",
		"lost_reason",
	}
)


def erased_person(request: str) -> str:
	return f"Erased person {request}"


def erased_content(request: str) -> str:
	return f"Content erased {request}"


def erased_file(request: str) -> str:
	return f"File erased {request}"


def scrub_identifiers(text: str | None, emails: set[str], phones: set[str], placeholder: str) -> str:
	"""Replace the given emails (case-insensitive) and phone numbers (any format) in `text`.

	`emails` and `phones` are already normalized. All spans are located in the original
	text and replaced together, so offsets stay valid and one replacement cannot hide
	another match. Where spans overlap, the earlier one wins, and at the same start the
	longer one wins.
	"""
	if not text:
		return ""

	spans: list[tuple[int, int]] = []

	for email in emails:
		if email:
			pattern = _EMAIL_START + re.escape(email) + _EMAIL_END
			spans.extend(m.span() for m in re.finditer(pattern, text, flags=re.IGNORECASE))

	if phones:
		for match in phonenumbers.PhoneNumberMatcher(
			text, PHONE_REGION, leniency=phonenumbers.Leniency.POSSIBLE
		):
			if normalize_identifier("Phone", match.raw_string) in phones:
				spans.append((match.start, match.end))

	out: list[str] = []
	pos = 0
	for start, end in sorted(spans, key=lambda span: (span[0], -span[1])):
		if start < pos:
			continue
		out.append(text[pos:start])
		out.append(placeholder)
		pos = end
	out.append(text[pos:])
	return "".join(out)


# Deal personal field -> keys of the person's value sets it is compared against.
DEAL_FIELD_SOURCES: dict[str, tuple[str, ...]] = {
	"first_name": ("first_name",),
	"last_name": ("last_name",),
	"salutation": ("salutation",),
	"gender": ("gender",),
	"linkedin": ("linkedin",),
	"twitter": ("twitter",),
	"facebook": ("facebook",),
	"lead_name": ("lead_name", "full_name"),
	"job_title": ("job_title", "designation"),
}


def _text(value: Any) -> str:
	return value.strip() if isinstance(value, str) else ""


def deal_fields_to_blank(
	deal: dict, her_values: dict[str, set[str]], emails: set[str], phones: set[str]
) -> list[str]:
	"""Names of the deal fields whose value belongs to the person being erased.

	Name-like fields compare stripped and case-folded; email and phones are normalized.
	Empty values are never listed.
	"""
	fields: list[str] = []

	if _text(deal.get("email")) and normalize_identifier("Email", deal["email"]) in emails:
		fields.append("email")

	for key in ("mobile_no", "phone"):
		if _text(deal.get(key)) and normalize_identifier("Phone", deal[key]) in phones:
			fields.append(key)

	for field, sources in DEAL_FIELD_SOURCES.items():
		value = _text(deal.get(field)).casefold()
		if value and any(value in her_values.get(source, ()) for source in sources):
			fields.append(field)

	return fields


def replace_addresses(header: str | None, emails: set[str], placeholder: str) -> str:
	"""Replace each address in `header` that is in `emails`, with its display name, by `placeholder`.

	A header none of whose addresses match is returned unchanged. Otherwise the other
	addresses are re-joined with ", " as `name <addr>` (name quoted only when it has
	specials, never RFC 2047 encoded) or bare `addr`. A header that cannot be parsed
	falls back to plain-text identifier scrubbing.
	"""
	if not header:
		return ""

	parsed = [(name, addr) for name, addr in getaddresses([header]) if name or addr]
	if not parsed:
		return scrub_identifiers(header, emails, set(), placeholder)
	if not any(normalize_email(addr) in emails for _, addr in parsed):
		return header

	parts: list[str] = []
	for name, addr in parsed:
		if normalize_email(addr) in emails:
			parts.append(placeholder)
		else:
			parts.append(_format_address(name, addr))
	return ", ".join(parts)


_ADDRESS_SPECIALS = set('()<>@,:;.[]"\\')


def _format_address(name: str, addr: str) -> str:
	"""`name <addr>` without charset encoding; the name is quoted only if it contains specials."""
	if not name:
		return addr
	if any(ch in _ADDRESS_SPECIALS for ch in name):
		name = '"' + name.replace("\\", "\\\\").replace('"', '\\"') + '"'
	return f"{name} <{addr}>" if addr else name


def _scrub_pairs(pairs: Any, should_scrub: Callable[[str, Any], bool], placeholder: str) -> None:
	"""Scrub `[[field, old, new], ...]` in place (on an already copied structure)."""
	if not isinstance(pairs, list):
		return
	for entry in pairs:
		if isinstance(entry, list) and len(entry) >= 3 and isinstance(entry[0], str):
			for i in (1, 2):
				if should_scrub(entry[0], entry[i]):
					entry[i] = placeholder


def scrub_version_data(data: dict, should_scrub: Callable[[str, Any], bool], placeholder: str) -> dict:
	"""Return a copy of a Version `data` dict with the values the predicate flags replaced.

	`should_scrub(field, value)` decides per value. Entries of unexpected shape are left alone.
	"""
	out = copy.deepcopy(data)
	if not isinstance(out, dict):
		return out

	_scrub_pairs(out.get("changed"), should_scrub, placeholder)

	for key in ("added", "removed"):
		rows = out.get(key)
		if not isinstance(rows, list):
			continue
		for entry in rows:
			if isinstance(entry, list) and len(entry) >= 2 and isinstance(entry[1], dict):
				row = entry[1]
				for field in row:
					if isinstance(field, str) and should_scrub(field, row[field]):
						row[field] = placeholder

	rows = out.get("row_changed")
	if isinstance(rows, list):
		for entry in rows:
			if isinstance(entry, list) and len(entry) >= 4:
				_scrub_pairs(entry[3], should_scrub, placeholder)

	return out
