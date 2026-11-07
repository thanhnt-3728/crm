# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Fixtures for the inbound-email privacy tests."""

import frappe

from crm.privacy.tests.make_test_user import RequestTestCase

EMAIL = "marisol.vega@example.com"
SENDER = "Marisol Vega <Marisol.Vega@Example.COM>"
REQUEST, LEAD, COMMUNICATION = "CRM Erasure Request", "CRM Lead", "Communication"
NOTICE_KEYS = "crm_dnc_inbound_notice"
NOTICE = "An email from an erased person arrived. Open it to decide what to do."


class InboundTestCase(RequestTestCase):
	def setUp(self):
		super().setUp()
		frappe.cache.delete_keys(NOTICE_KEYS)
		self.account = make_email_account()

	def tearDown(self):
		frappe.cache.delete_keys(NOTICE_KEYS)  # the once-a-day marks live in the cache, outside the rollback
		super().tearDown()

	def receive(self, sender: str = SENDER, **values):
		"""Insert a received email the way mailbox sync does; returns the saved Communication."""
		doc = incoming_email(sender, self.account, **values)
		doc.insert(ignore_permissions=True)
		return doc

	def reference(self, doc) -> tuple:
		"""What the database says the email is linked to (the in-memory copy can be ahead of it)."""
		return tuple(frappe.db.get_value(COMMUNICATION, doc.name, ["reference_doctype", "reference_name"]))

	def leads_for(self, email: str = EMAIL) -> list:
		return frappe.get_all(LEAD, {"email": email}, pluck="name")

	def notices(self) -> list:
		return frappe.get_all(
			"CRM Notification",
			{"type": "Compliance", "to_user": self.compliance},
			["reference_doctype", "reference_name", "notification_text"],
		)


def make_email_account(create_lead: int = 1, create_contact: int = 0) -> str:
	"""A minimal incoming Email Account; `create_lead` is the CRM switch on it. Frappe turns `create_contact`
	on by default and logs an Error Log for each contact the block refuses, so tests opt in."""
	account = frappe.get_doc(
		{
			"doctype": "Email Account",
			"email_account_name": f"Privacy test {frappe.generate_hash(length=6)}",
			"email_id": f"privacy-{frappe.generate_hash(length=6)}@example.org",
			"enable_incoming": 1,
			"create_lead_from_incoming_email": create_lead,
			"create_contact": create_contact,
		}
	)
	account.flags.ignore_mandatory = True
	account.flags.ignore_validate = True
	account.insert(ignore_permissions=True)
	return account.name


def incoming_email(sender: str, account: str | None = None, **values):
	"""A received Communication, not yet inserted."""
	return frappe.get_doc(
		{
			"doctype": "Communication",
			"communication_type": "Communication",
			"communication_medium": "Email",
			"sent_or_received": "Received",
			"subject": "Hello",
			"content": "Please call me back.",
			"sender": sender,
			"email_account": account,
			**values,
		}
	)
