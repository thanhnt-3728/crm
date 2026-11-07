# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Her identifiers and the request number inside free text (notifications, queued mail, raw email, logs).

Whole values only (RT-4): `m.vega@example.com` is not found inside `adam.vega@example.com` or `m.vega@example.com.au`,
and `+15305550101` is not found inside `+153055501019`. `prefilter_terms` gives the substrings for a SQL `LIKE`
prefilter; every candidate is then confirmed here. Pure: no database.
"""

import re

from crm.privacy.erasure.value_matcher import Identifiers, same_phone

PHONE_CANDIDATE = re.compile(r"\+?\d[\d\s().\-/]{5,}\d")
PHONE_TAIL = 4  # digits kept for the SQL prefilter; every spelling of a number ends the same way


def _email_pattern(email: str) -> re.Pattern:
	return re.compile(rf"(?<![\w.+-]){re.escape(email)}(?![\w-]|\.\w)", re.IGNORECASE)


def mentions_identifier(text: str | None, identifiers: Identifiers) -> bool:
	"""Whether `text` contains one of the identifiers as a whole address or a whole phone number."""
	if not text or not identifiers:
		return False
	if any(_email_pattern(email).search(text) for email in identifiers.emails):
		return True
	return bool(identifiers.phones) and any(
		same_phone(match.group(), identifiers.phones) for match in PHONE_CANDIDATE.finditer(text)
	)


def mentions_number(text: str | None, number: str) -> bool:
	"""Whether the request number appears as a whole token (`PDR-0001` is not in `PDR-00010`)."""
	return bool(text) and bool(re.search(rf"(?<![A-Za-z0-9]){re.escape(number)}(?!\d)", text))


def prefilter_terms(identifiers: Identifiers) -> list[str]:
	"""Substrings to prefilter free-text columns with LIKE: each email, and the last digits of each phone."""
	tails = {re.sub(r"\D", "", phone)[-PHONE_TAIL:] for phone in identifiers.phones}
	return sorted(identifiers.emails) + sorted(tail for tail in tails if tail)
