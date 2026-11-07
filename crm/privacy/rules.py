"""Placeholder text and identifier scrubbing for privacy (erasure) requests."""

import re

import phonenumbers

from crm.privacy.identifiers import PHONE_REGION, normalize_identifier


# A confirmed email matches only as a whole address: not glued to a preceding address
# character, and not continued by a longer name or domain (a@b.example.org, a@b.example-x).
_EMAIL_START = r"(?<![\w.+%-])"
_EMAIL_END = r"(?![\w-])(?!\.\w)"


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
		for match in phonenumbers.PhoneNumberMatcher(text, PHONE_REGION, leniency=phonenumbers.Leniency.POSSIBLE):
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
