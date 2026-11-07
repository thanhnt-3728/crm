# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""What a request response may show a user who cannot read every record on it (RT-5)."""

from crm.privacy.matching import can_read


def hide_unreadable(data: dict, user: str) -> None:
	"""Drop, in place, the match rows for records `user` cannot read and the identifier rows that were pulled from
	such a record: both name the record, and an identifier is the record's own phone or email."""
	data["matches"] = [m for m in data["matches"] if can_read(user, m.reference_doctype, m.reference_name)]
	data["identifiers"] = [
		i
		for i in data["identifiers"]
		if not i.source_doctype or can_read(user, i.source_doctype, i.source_name)
	]
