# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt
"""Her phone numbers: normalization at log time and matching against stored values

Normalized form: E.164, plus ";ext=<digits>" when the number has an extension. A number without
a country code takes the site's region (System Settings country, as telephony lookup does);
when the site has no country it is rejected, never parsed against a fallback region.
Matching works on digit groups, so `(415) 555-0123`, `+1 415-555-0123` and `001 415 555 0123`
are one number while `+44 415 555 0123` is not; extensions must agree when both sides have one.
"""

import re
from dataclasses import dataclass

import frappe
import phonenumbers
from phonenumbers import NumberParseException
from phonenumbers import PhoneNumberFormat as PNF

EXTENSION_MARK = ";ext="
# A run of digit groups joined by short separators: "(415) 555-0123", "+1 415.555.0123"
_DIGIT_RUN = re.compile(r"\+?\d+(?:[ \t().\-/]{1,3}\+?\d+)*")
_DIGIT_GROUP = re.compile(r"\+?\d+")
_EXTENSION = re.compile(r"\s*(?:;\s*ext=|ext\.?|extension|x|#)\s*(\d{1,7})", re.IGNORECASE)
_MAX_GROUPS = 6  # a phone spelled with more groups than this is not one we try to match


@dataclass(frozen=True)
class Phone:
	e164: str
	national: str  # national significant number: keeps Italy's leading zero
	country_code: str
	extension: str = ""

	@property
	def normalized(self) -> str:
		return self.e164 + (EXTENSION_MARK + self.extension if self.extension else "")

	@property
	def spellings(self) -> frozenset[str]:
		"""Digit strings that are this number: national, with country code, with trunk zero"""
		return frozenset({self.national, self.country_code + self.national, "0" + self.national})

	def matches(self, text: str) -> bool:
		"""True when `text` spells this number (a country code, if given, must be this one)"""
		for run in _DIGIT_RUN.finditer(text):
			groups = _DIGIT_GROUP.findall(run.group())
			found = _EXTENSION.match(text, run.end())
			for end in _window_ends(groups, self.spellings):
				extension = found.group(1) if found and end == len(groups) else ""
				if not (self.extension and extension and extension != self.extension):
					return True
		return False


def normalize_phone_identifier(value: str | None, region: str | None = None) -> str:
	"""Normalized form of a valid phone number; ValueError for empty, invalid or ambiguous numbers"""
	raw = (value or "").strip()
	raw, _mark, extension = raw.partition(EXTENSION_MARK)
	if raw.startswith("00"):  # international prefix used outside North America
		raw = "+" + raw[2:]
	if not re.search(r"\d", raw):
		raise ValueError("not a valid phone number")
	region = None if raw.startswith("+") else (region or site_region())
	if not raw.startswith("+") and not region:
		raise ValueError("include the country code (the site has no country set)")
	try:
		parsed = phonenumbers.parse(raw, region)
	except NumberParseException:
		raise ValueError("not a valid phone number; include the country code") from None
	if not phonenumbers.is_valid_number(parsed):
		raise ValueError("not a valid phone number; include the country code")
	extension = extension or parsed.extension or ""
	if extension and not extension.isdigit():
		raise ValueError("not a valid phone extension")
	return phonenumbers.format_number(parsed, PNF.E164) + (EXTENSION_MARK + extension if extension else "")


def phone_from_normalized(normalized: str) -> Phone:
	e164, _mark, extension = normalized.partition(EXTENSION_MARK)
	parsed = phonenumbers.parse(e164, None)
	return Phone(
		e164=e164,
		national=phonenumbers.national_significant_number(parsed),
		country_code=str(parsed.country_code),
		extension=extension,
	)


def site_region() -> str | None:
	"""ISO region of System Settings country; None when unset (no fallback region in this path)"""
	country = frappe.db.get_single_value("System Settings", "country")
	if not country:
		return None
	from frappe.geo.country_info import get_country_info

	code = get_country_info(country).get("code")
	return code.upper() if code else None


def _window_ends(groups: list[str], spellings: frozenset[str]):
	"""Indexes (exclusive) where a window of `groups` spelling one of `spellings` ends"""
	for start in range(len(groups)):
		# a "+44" or "0044" group is a country code: the number after it is not hers unless it is
		if start and groups[start - 1].startswith(("+", "00")):
			continue
		digits = ""
		for end in range(start, min(start + _MAX_GROUPS, len(groups))):
			digits += groups[end].lstrip("+")
			candidate = digits[2:] if digits.startswith("00") else digits
			if candidate in spellings:
				yield end + 1
