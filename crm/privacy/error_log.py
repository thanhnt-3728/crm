# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""The privacy code's one way to write an Error Log row (V1).

`frappe.log_error` stores the request's `form_dict` as metadata, and a deal save or a webhook body holds a
person's email, phone or message text. It also reads the live exception for its fingerprint and, with Sentry on,
reports it. This writes the same row with neutral metadata and no exception: call it after leaving the `except`
block, with the request number or a fixed title and a class name as the text.
"""

import frappe

NEUTRAL_METADATA = "{}"


def log_privacy_error(title: str, text: str, reference_doctype=None, reference_name=None) -> None:
	log = frappe.get_doc(
		doctype="Error Log",
		method=title,
		error=text,
		reference_doctype=reference_doctype,
		reference_name=reference_name,
		metadata=NEUTRAL_METADATA,
	)
	if frappe.flags.read_only:
		log.deferred_insert()
	else:
		log.insert(ignore_permissions=True)
