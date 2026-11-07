# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Compliance sends the outcome email of an erasure request. The rules live in `crm.privacy.outcome_email`."""

import frappe

from crm.privacy import outcome_email


@frappe.whitelist()
def send_outcome_email(name: str, subject: str, content: str, recipients: list) -> dict:
	"""Send the answer to the requester and attach it to the request. Compliance only, while the request is Erased or
	Declined and no erasure job runs. `recipients` must be the request's own non-excluded email identifiers.
	Returns `{name}` of the Communication."""
	return outcome_email.send(name, subject, content, recipients, frappe.session.user)
