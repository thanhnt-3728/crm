# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Text of the checklist items the erasure adds by itself (design 5.7, V1). One home, so the approval preview
promises exactly what the job later writes. Not translated: it is written into the request."""

TWILIO_ITEM = "Delete recordings at provider (Twilio)"


def data_import_item(count: int) -> str:
	return f"Check Data Import files for this person ({count} import{'' if count == 1 else 's'})"


def recording_item(provider: str) -> str:
	"""One item per provider that holds recordings; a number with no known provider is taken for Twilio."""
	return TWILIO_ITEM if provider == "Twilio" else f"Delete recordings at provider ({provider})"
