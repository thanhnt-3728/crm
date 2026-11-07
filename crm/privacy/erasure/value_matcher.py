# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Whole-value matching of her identifiers inside text (design 5.6, RT-4).

Pure: no database. An identifier matches only as the whole value of a field or as a whole address in an address
list, never as a part of a longer string, so `adam.vega@example.com` is not `m.vega@example.com` and
`+153055501019` is not `+15305550101`. `like_literal` is for the SQL prefilter only; callers still confirm every
candidate with these functions.
"""

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from email.utils import getaddresses

import frappe

from crm.privacy.identifiers import PHONE_REGION, normalize_email, normalize_identifier
from crm.utils import normalize_phone

PHONE_LIKE = re.compile(r"^[\d\s().+/-]+$")
SEPARATORS = ",;"
MAX_ADDRESS_LIST = 2000  # a longer string is not an address list


@dataclass(frozen=True)
class Identifiers:
	"""Her non-excluded identifiers in canonical form: lowercase emails and E.164 phones."""

	emails: frozenset = frozenset()
	phones: frozenset = frozenset()

	@classmethod
	def of(cls, pairs: Iterable[tuple[str, str | None]]) -> "Identifiers":
		"""`pairs` of (kind, value); kind is "email" or "phone" in any case. Empty values are dropped."""
		emails, phones = set(), set()
		for kind, value in pairs:
			kind = (kind or "").lower()
			normalized = normalize_identifier(kind, value)
			if normalized:
				(emails if kind == "email" else phones).add(normalized)
		return cls(frozenset(emails), frozenset(phones))

	def __bool__(self) -> bool:
		return bool(self.emails or self.phones)


def like_literal(value: str) -> str:
	"""`value` with the LIKE wildcards and the escape character made literal."""
	return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def parse_addresses(text: str | None) -> list[tuple[str, str]]:
	"""(display name, lowercase address) for each entry of a comma or semicolon separated address list."""
	if not text or len(text) > MAX_ADDRESS_LIST:
		return []
	return [
		(name, normalize_email(address))
		for name, address in getaddresses([text.replace(";", ",")])
		if address
	]


def has_address(text: str | None, emails: Iterable[str]) -> bool:
	"""Whether one of `emails` (normalized) is a whole address of the list."""
	wanted = set(emails)
	return any(address in wanted for _name, address in parse_addresses(text))


def _split_list(text: str) -> list[str]:
	"""Entries and separators of an address list, in order, so a join gives the text back. A separator inside
	quotes or angle brackets belongs to the entry."""
	parts, current, quoted, angled = [], "", False, False
	for char in text:
		if char == '"':
			quoted = not quoted
		elif char == "<" and not quoted:
			angled = True
		elif char == ">" and not quoted:
			angled = False
		if char in SEPARATORS and not quoted and not angled:
			parts += [current, char]
			current = ""
		else:
			current += char
	return [*parts, current]


def replace_addresses(text: str | None, emails: Iterable[str], placeholder: str) -> str | None:
	"""`text` with each of her addresses (display name and all) replaced by `placeholder`; other entries keep
	their text, spacing and separators."""
	if not text or not has_address(text, emails):
		return text
	wanted = set(emails)
	out = []
	for part in _split_list(text):
		entries = parse_addresses(part) if part and part not in SEPARATORS else []
		if entries and entries[0][1] in wanted:
			padding = part[: len(part) - len(part.lstrip())]
			part = padding + placeholder
		out.append(part)
	return "".join(out)


def same_phone(stored: str | None, phones: Iterable[str]) -> bool:
	"""Whether a stored free-text number is one of `phones` (E.164), read as a US number or in the site's region.
	Text with anything but digits and phone punctuation is not a number."""
	if not stored or not PHONE_LIKE.match(stored.strip()):
		return False
	return bool({normalize_phone(stored, region=PHONE_REGION), normalize_phone(stored)} & set(phones))


def _norm(value) -> str:
	return value.strip().lower() if isinstance(value, str) else ""


def holds_her_value(value, identifiers: Identifiers, same_field_values: Iterable[str] = ()) -> bool:
	"""A value that is hers: a whole identifier, or equal (trimmed, any case) to the same field's value on one of
	her confirmed records (`same_field_values`)."""
	text = _norm(value)
	if not text:
		return False
	return (
		text in identifiers.emails
		or same_phone(value, identifiers.phones)
		or text in {_norm(v) for v in same_field_values}
	)


def holds_identifier(obj, identifiers: Identifiers) -> bool:
	"""Whether a parsed JSON document holds an identifier as a whole field value (or a whole address of an
	address-list field) anywhere in it. A longer text that merely contains one does not count."""
	if isinstance(obj, dict):
		return any(holds_identifier(v, identifiers) for v in obj.values())
	if isinstance(obj, list):
		return any(holds_identifier(v, identifiers) for v in obj)
	if not isinstance(obj, str):
		return False
	return (
		_norm(obj) in identifiers.emails
		or ("@" in obj and has_address(obj, identifiers.emails))
		or same_phone(obj, identifiers.phones)
	)
