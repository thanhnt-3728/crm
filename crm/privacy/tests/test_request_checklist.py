# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""The checklist and the acknowledgment (phase 06; design 5.7, 5.2): Compliance only, open requests only."""

import frappe
from frappe.utils import add_days, getdate, today

from crm.api.erasure_requests import get_request
from crm.api.erasure_review import add_checklist_item, mark_acknowledged, set_checklist_item_done
from crm.privacy.tests.make_test_user import RequestTestCase, as_user, force_request, make_request

DOCTYPE = "CRM Erasure Request"
STATUSES = ("Logged", "Awaiting sign-off", "On Hold", "Erased", "Declined", "Closed")


class ChecklistCase(RequestTestCase):
	def setUp(self):
		super().setUp()
		self.request = make_request(self.logger, date_received=add_days(today(), -5))
		force_request(self.request, status="Erased")

	def add(self, text="Delete recordings at provider (Twilio)", user=None, name=None):
		return as_user(user or self.compliance, add_checklist_item, name or self.request, text)

	def tick(self, row, done=True, user=None):
		return as_user(user or self.compliance, set_checklist_item_done, self.request, row, done)

	def acknowledge(self, on=None, user=None):
		return as_user(user or self.compliance, mark_acknowledged, self.request, on)

	def row(self, text="Delete recordings at provider (Twilio)") -> str:
		return next(r["name"] for r in self.add(text)["checklist"] if r["description"] == text)

	def items(self):
		return frappe.get_doc(DOCTYPE, self.request).checklist


class TestWhoMay(ChecklistCase):
	def test_nobody_but_compliance(self):
		row = self.row()
		for user in (self.other, self.manager, self.logger, "Administrator"):
			with self.subTest(user=user):
				for call in (
					lambda: self.add("x", user),
					lambda: self.tick(row, True, user),
					lambda: self.acknowledge(None, user),
				):
					with self.assertRaises(frappe.PermissionError):
						call()
		self.assertEqual([(i.description, i.done) for i in self.items()],
			[("Delete recordings at provider (Twilio)", 0)])  # fmt: skip
		self.assertFalse(frappe.db.get_value(DOCTYPE, self.request, "acknowledgment_sent"))


class TestChecklist(ChecklistCase):
	def test_an_item_is_added_open_and_by_hand(self):
		result = self.add("Remove from the mailing provider")
		item = result["checklist"][0]
		self.assertEqual(
			(item["description"], item["done"], item["auto_added"]),
			("Remove from the mailing provider", 0, 0),
		)

	def test_the_description_is_trimmed_required_and_bounded(self):
		self.add("  padded  ")
		self.assertEqual(self.items()[0].description, "padded")
		for text in ("", "   ", None, "x" * 501):
			with self.subTest(text=text), self.assertRaises(frappe.ValidationError):
				self.add(text)

	def test_ticking_records_who_and_when_and_unticking_clears_it(self):
		row = self.row()
		self.tick(row)
		item = self.items()[0]
		self.assertEqual((item.done, item.done_by), (1, self.compliance))
		self.assertEqual(getdate(item.done_on), getdate(today()))
		self.tick(row, False)
		item = self.items()[0]
		self.assertEqual((item.done, item.done_by, item.done_on), (0, None, None))

	def test_a_row_that_is_not_on_the_request_is_refused(self):
		other = make_request(self.logger)
		force_request(other, status="Erased")
		foreign = next(r["name"] for r in self.add("elsewhere", name=other)["checklist"])
		for row in ("nope", foreign):
			with self.subTest(row=row), self.assertRaises(frappe.ValidationError):
				self.tick(row)

	def test_it_works_before_the_erasure_and_after_a_decline(self):
		for status in ("Logged", "Awaiting sign-off", "On Hold", "Declined"):
			with self.subTest(status=status):
				force_request(self.request, status=status)
				self.tick(self.row(f"item {status}"))

	def test_a_closed_request_or_a_running_job_refuses(self):
		row = self.row()
		for values in ({"status": "Closed"}, {"status": "Erased", "erasure_job_status": "Running"}):
			with self.subTest(values=values):
				force_request(self.request, **values)
				for call in (lambda: self.add("late"), lambda: self.tick(row)):
					with self.assertRaises(frappe.ValidationError):
						call()
		self.assertEqual(len(self.items()), 1)


class TestAcknowledgment(ChecklistCase):
	def test_it_sets_the_flag_and_the_date(self):
		received = add_days(today(), -2)
		self.acknowledge(str(received))
		values = frappe.db.get_value(
			DOCTYPE, self.request, ["acknowledgment_sent", "acknowledged_on"], as_dict=True
		)
		self.assertEqual(
			(values.acknowledgment_sent, getdate(values.acknowledged_on)), (1, getdate(received))
		)

	def test_no_date_means_today(self):
		self.acknowledge()
		self.assertEqual(
			getdate(frappe.db.get_value(DOCTYPE, self.request, "acknowledged_on")), getdate(today())
		)

	def test_a_date_before_receipt_or_in_the_future_is_refused(self):
		for day in (add_days(today(), -6), add_days(today(), 1), "nonsense"):
			with self.subTest(day=day), self.assertRaises(frappe.ValidationError):
				self.acknowledge(str(day))
		self.assertFalse(frappe.db.get_value(DOCTYPE, self.request, "acknowledgment_sent"))

	def test_the_receipt_day_and_today_are_accepted(self):
		self.acknowledge(str(add_days(today(), -5)))

	def test_it_cannot_be_recorded_twice(self):
		self.acknowledge()
		with self.assertRaises(frappe.ValidationError):
			self.acknowledge()

	def test_a_closed_request_refuses(self):
		force_request(self.request, status="Closed")
		with self.assertRaises(frappe.ValidationError):
			self.acknowledge()


class TestMatchesTheActionFlags(ChecklistCase):
	"""Each endpoint succeeds exactly when `get_request` says `can`: the UI and the server agree."""

	def test_checklist_and_acknowledgment_follow_the_flags(self):
		for status in STATUSES:
			for job in ("", "Running"):
				with self.subTest(status=status, job=job):
					force_request(self.request, status=status, erasure_job_status=job, acknowledgment_sent=0)
					can = as_user(self.compliance, get_request, self.request)["can"]
					for flag, call in (
						("manage_checklist", lambda: self.add(f"{status}{job}")),
						("mark_acknowledged", lambda: self.acknowledge()),
					):
						try:
							call()
							allowed = True
						except frappe.ValidationError:
							allowed = False
						self.assertEqual(allowed, can[flag], flag)
						force_request(self.request, acknowledgment_sent=0, acknowledged_on=None)
