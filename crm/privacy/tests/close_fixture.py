# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""An Erased request with everything around it that closing must deal with (phase 06): her mail, a file, a
comment, a queued email, a checklist and a contract reference."""

import os
from unittest.mock import patch

import frappe
from frappe.utils import add_days, now_datetime, today

from crm.api.erasure_review import close_request
from crm.privacy.request_close import finish_closed_files
from crm.privacy.request_status import server_write
from crm.privacy.tests.erasure_fixture import remove_bytes
from crm.privacy.tests.erasure_fixture_files import file_doc
from crm.privacy.tests.inbound_helpers import incoming_email, make_email_account
from crm.privacy.tests.make_test_user import (
	RequestTestCase,
	add_match,
	as_user,
	force_request,
	make_lead,
	make_request,
)

DOCTYPE = "CRM Erasure Request"
TODAY = object()  # "answered today", as opposed to None
EMAIL, OTHER = "m.vega@example.com", "jon.park@sierra.example.com"
HER_VALUES = ("marisol", "vega", EMAIL, "5305550101", "delete my data", "id-card")


def add_rows(name: str, table: str, rows: list[dict]) -> None:
	doc = frappe.get_doc(DOCTYPE, name)
	for row in rows:
		doc.append(table, row)
	with server_write():
		doc.save(ignore_permissions=True)


def holds_her_values(name: str) -> list[str]:
	"""Which of her values are still on the request row or one of its child rows."""
	text = frappe.as_json(frappe.get_doc(DOCTYPE, name)).lower()
	return [bit for bit in HER_VALUES if bit in text]


class CloseTestCase(RequestTestCase):
	"""`self.request` is Erased with a finished checklist; `self.mail`, `self.sent`, `self.file`, `self.comment`
	and `self.queued` are the rows attached to it."""

	def setUp(self):
		self.addCleanup(
			frappe.db.rollback
		)  # a failed setUp skips tearDown, and the next test must start clean
		super().setUp()
		enqueue = patch("frappe.enqueue")  # no worker in the test bench
		enqueue.start()
		self.addCleanup(enqueue.stop)
		self.addCleanup(remove_bytes)
		self.request = make_request(
			self.logger,
			date_received=add_days(today(), -20),
			emails=[EMAIL],
			phones=["+15305550101"],
			original_message="Please delete my data. Marisol Vega",
		)
		add_match(self.request, "CRM Lead", make_lead(email=EMAIL, mobile_no="+15305550101"))
		add_rows(self.request, "checklist", [self.item("Delete recordings (Twilio) for Marisol Vega", 1)])
		add_rows(self.request, "contract_references", [{"reference": "CT-1001"}])
		force_request(self.request, status="Erased", acknowledgment_sent=1, erased_on=now_datetime())
		self.attach_records()

	def item(self, text: str, done: int) -> dict:
		return {"description": text, "done": done, "done_by": self.compliance if done else None}

	def attach_records(self) -> None:
		account = make_email_account(create_lead=0)
		self.mail = self.attach(
			incoming_email(f"Marisol Vega <{EMAIL}>", account, subject="Erase me Marisol")
		)
		self.sent = self.attach(
			incoming_email(
				self.compliance,
				account,
				sent_or_received="Sent",
				recipients=f"Marisol Vega <{EMAIL}>, {OTHER}",
				subject="Your request",
				content="Dear Marisol Vega, done.",
			)
		)
		self.file = file_doc(DOCTYPE, self.request, "id-card-marisol.txt")
		self.mail_file = file_doc("Communication", self.mail, "scan-from-email.txt")
		self.comment = frappe.get_doc(
			{
				"doctype": "Comment",
				"comment_type": "Info",
				"reference_doctype": DOCTYPE,
				"reference_name": self.request,
				"content": "Marisol Vega phoned",
			}
		).insert(ignore_permissions=True)
		self.queued = frappe.get_doc(
			{
				"doctype": "Email Queue",
				"sender": self.compliance,
				"message": "Dear Marisol Vega",
				"reference_doctype": DOCTYPE,
				"reference_name": self.request,
				"communication": self.sent,
				"status": "Sent",  # an outcome email that went out; an unsent one blocks the close
				"recipients": [{"recipient": EMAIL}],
			}
		).insert(ignore_permissions=True)

	def queue_email(self, status: str, **values) -> str:
		"""A queued email for the outcome email `self.sent` (or, with `communication=None`, about the request only)."""
		values.setdefault("communication", self.sent)
		return (
			frappe.get_doc(
				{
					"doctype": "Email Queue",
					"sender": self.compliance,
					"message": "Dear Marisol Vega",
					"reference_doctype": DOCTYPE,
					"reference_name": self.request,
					"status": status,
					"recipients": [{"recipient": EMAIL}],
					**values,
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	def attach(self, doc) -> str:
		doc.reference_doctype, doc.reference_name = DOCTYPE, self.request
		doc.insert(ignore_permissions=True)
		return doc.name

	def close(self, user=None, outcome="Completed", reason=None, answered=TODAY, name=None):
		answered = today() if answered is TODAY else answered
		answered = str(answered) if answered is not None else None
		return as_user(
			user or self.compliance, close_request, name or self.request, answered, outcome, reason
		)

	def stored(self, *fields, name=None):
		return frappe.db.get_value(DOCTYPE, name or self.request, list(fields), as_dict=True)

	def finish_after_commit(self) -> None:
		"""Run what close queued for after the commit, without committing the test's rows."""
		with patch("frappe.db.commit"):
			frappe.db.after_commit.run()

	@staticmethod
	def byte_deletions_queued() -> int:
		"""How many "delete the bytes of a closed request" callbacks wait for the commit."""
		return sum(getattr(f, "func", None) is finish_closed_files for f in frappe.db.after_commit._functions)

	@staticmethod
	def bytes_exist(doc) -> bool:
		return os.path.exists(doc.get_full_path())
