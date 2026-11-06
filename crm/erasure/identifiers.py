# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt
"""Her identifiers (emails, phones): normalization at log time and matching against stored values

Emails match exactly, case-insensitively, as whole addresses: `ann@x.com` never matches
`joann@x.com`, `jo=ann@x.com` or `ann@x.com.au`. Address-list columns are split and parsed
(`parse_addr`); free text is searched with address-character boundaries. Phones: see
`phone_numbers`. Invalid values are rejected when the request is logged, because an identifier
that cannot be normalized would silently under-match.
"""

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from functools import cache

from frappe.utils import parse_addr

from crm.erasure.phone_numbers import (
	Phone,
	normalize_phone_identifier,
	phone_from_normalized,
	site_region,
)

EMAIL, PHONE = "Email", "Phone"

_EMAIL = re.compile(r"[a-z0-9._%+'-]+@[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)+")
_LIST_SEPARATORS = re.compile(r"[,;\n]")
# Characters that may sit inside an address: one of them right before or after hers means a
# different, longer address. An apostrophe counts only after a letter ("o'ann@" is not hers,
# "'ann@x.com'" in a Python repr is).
_BEFORE = r"(?<![\w!#$%&*+/=?^`{|}~.-])(?<!\w')"
_AFTER = r"(?![\w-]|\.[\w-])"


def normalize_email(value: str | None) -> str:
	"""Lower-cased, trimmed address; ValueError when it is not a single plain address"""
	email = (value or "").strip().lower()
	if not _EMAIL.fullmatch(email):
		raise ValueError("not a valid email address")
	return email


def identifier_rows(emails: Iterable[str], phones: Iterable[str], region: str | None = None) -> list[dict]:
	"""Rows for `CRM Erasure Request.identifiers`, de-duplicated on the normalized value

	Errors name the position of a bad value, never the value itself (it may be personal data).
	"""
	rows, seen = [], set()
	for kind, values, normalize in (
		(EMAIL, emails, normalize_email),
		(PHONE, phones, lambda v: normalize_phone_identifier(v, region)),
	):
		for position, value in enumerate(values or [], start=1):
			try:
				normalized = normalize(value)
			except ValueError as e:
				raise ValueError(f"{kind} {position}: {e}") from None
			if (kind, normalized) not in seen:
				seen.add((kind, normalized))
				rows.append({"kind": kind, "value": value, "normalized": normalized})
	return rows


@dataclass(frozen=True)
class Identifiers:
	emails: frozenset[str] = frozenset()
	phones: tuple[Phone, ...] = ()

	@classmethod
	def from_rows(cls, rows: Iterable, region: str | None = None) -> "Identifiers":
		"""From identifier rows (dicts or child docs); re-normalizes, so a bad row raises ValueError"""
		emails, phones = set(), {}
		for row in rows or []:
			kind, value = _get(row, "kind"), _get(row, "normalized") or _get(row, "value")
			if kind == EMAIL:
				emails.add(normalize_email(value))
			elif kind == PHONE:
				normalized = normalize_phone_identifier(value, region)
				phones[normalized] = phone_from_normalized(normalized)
			else:
				raise ValueError("unknown identifier kind")
		return cls(frozenset(emails), tuple(phones[key] for key in sorted(phones)))

	def __bool__(self) -> bool:
		return bool(self.emails or self.phones)

	@property
	def search_digits(self) -> tuple[str, ...]:
		"""National significant digits of each phone: the SQL LIKE prefilter on digits-only columns"""
		return tuple(dict.fromkeys(phone.national for phone in self.phones))

	def matches_email(self, value: str | None) -> bool:
		"""True when one address of an address-list column value (or a single address) is hers"""
		return bool(self.emails) and any(address in self.emails for address in addresses_in(value))

	def matches_phone(self, text: str | None) -> bool:
		"""True when `text` spells one of her numbers"""
		return bool(text) and any(phone.matches(str(text)) for phone in self.phones)

	def matches_text(self, text: str | None) -> bool:
		"""Scan free text or JSON (Version data, logs, queue rows) for any of her identifiers"""
		if not text:
			return False
		lowered = str(text).lower()
		return any(_email_pattern(email).search(lowered) for email in self.emails) or self.matches_phone(text)


def addresses_in(value: str | None) -> list[str]:
	"""Lower-cased addresses of an address list ("A <a@x.com>, b@y.com; c@z.com")"""
	if not value:
		return []
	addresses = (parse_addr(part)[1] for part in _LIST_SEPARATORS.split(str(value)) if part.strip())
	return [address.strip().lower() for address in addresses if address and "@" in address]


emails_in = addresses_in  # earlier name, kept for callers


@cache
def _email_pattern(email: str) -> re.Pattern:
	return re.compile(_BEFORE + re.escape(email) + _AFTER)


def _get(row, key: str):
	return row.get(key) if isinstance(row, Mapping) or hasattr(row, "get") else getattr(row, key, None)
