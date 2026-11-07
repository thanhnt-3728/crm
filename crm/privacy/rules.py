"""Placeholder text and identifier scrubbing for privacy (erasure) requests."""

import re

import phonenumbers

from crm.privacy.identifiers import PHONE_REGION, normalize_identifier


def erased_person(request: str) -> str:
	return f"Erased person {request}"


def erased_content(request: str) -> str:
	return f"Content erased {request}"


def erased_file(request: str) -> str:
	return f"File erased {request}"


def scrub_identifiers(
	text: str | None, emails: set[str], phones: set[str], placeholder: str
) -> str:
	"""Replace the given emails (case-insensitive) and phone numbers (any format) in `text`.

	`emails` and `phones` are already normalized. All spans are located in the original
	text and replaced together, so offsets stay valid and one replacement cannot hide
	another match. Where spans overlap, the earlier one wins.
	"""
	if not text:
		return ""

	spans: list[tuple[int, int]] = []

	for email in emails:
		if email:
			spans.extend(m.span() for m in re.finditer(re.escape(email), text, flags=re.IGNORECASE))

	if phones:
		for match in phonenumbers.PhoneNumberMatcher(text, PHONE_REGION):
			if normalize_identifier("Phone", match.raw_string) in phones:
				spans.append((match.start, match.end))

	out: list[str] = []
	pos = 0
	for start, end in sorted(spans):
		if start < pos:
			continue
		out.append(text[pos:start])
		out.append(placeholder)
		pos = end
	out.append(text[pos:])
	return "".join(out)
