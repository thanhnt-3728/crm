import frappe
from frappe.tests import IntegrationTestCase

from crm.fcrm.doctype.crm_deal.crm_deal import remove_contact
from crm.permissions.test_org_hierarchy import make_user
from crm.privacy.api import log_request, save_request, submit_request
from crm.privacy.hold import apply_hold, open_deals_for
from crm.privacy.reminders import notify
from crm.privacy.tests.factories import make_compliance_user, make_marisol, make_request


def _close(deal: str) -> None:
	frappe.get_doc("CRM Deal", deal).update(
		{"status": "Lost", "lost_reason": "Other", "lost_notes": "x"}
	).save()


class TestHold(IntegrationTestCase):
	def setUp(self):
		if not frappe.db.exists("CRM Lost Reason", "Other"):
			frappe.get_doc({"doctype": "CRM Lost Reason", "lost_reason": "Other"}).insert()

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def _submitted(self, m):
		name = log_request("Contact", m.contact)
		save_request(
			name,
			{"matches": [{"reference_doctype": "CRM Deal", "reference_name": m.open_deal, "confirmed": 1}]},
		)
		return submit_request(name)

	def test_open_deal_puts_on_hold_and_notifies_owner(self):
		make_user("owner@example.com", ["Sales User"])
		m = make_marisol()
		frappe.db.set_value("CRM Deal", m.open_deal, "deal_owner", "owner@example.com")
		out = self._submitted(m)
		self.assertEqual(out["status"], "On Hold")
		notice = frappe.db.get_value(
			"CRM Notification",
			{"to_user": "owner@example.com", "type": "Privacy", "reference_name": m.open_deal},
			["reference_doctype", "notification_type_doc", "message"],
			as_dict=True,
		)
		self.assertIsNotNone(notice)
		self.assertEqual(notice.reference_doctype, "CRM Deal")
		self.assertEqual(notice.notification_type_doc, out["name"])
		self.assertIn(out["name"], notice.message)
		self.assertIn(m.open_deal, notice.message)

	def test_removing_contact_releases_hold(self):
		m = make_marisol()
		name = self._submitted(m)["name"]
		remove_contact(m.open_deal, m.contact)
		self.assertEqual(frappe.db.get_value("CRM Erasure Request", name, "status"), "Awaiting Sign-off")

	def test_hold_stays_while_a_deal_is_still_open(self):
		m = make_marisol()
		name = self._submitted(m)["name"]
		self.assertEqual(open_deals_for(frappe.get_doc("CRM Erasure Request", name)), [m.open_deal])
		frappe.get_doc("CRM Deal", m.won_deal).save()  # an unrelated deal update leaves the hold alone
		self.assertEqual(frappe.db.get_value("CRM Erasure Request", name, "status"), "On Hold")

	def test_closing_the_deal_releases_hold(self):
		m = make_marisol()
		name = self._submitted(m)["name"]
		_close(m.open_deal)
		self.assertEqual(frappe.db.get_value("CRM Erasure Request", name, "status"), "Awaiting Sign-off")

	def test_won_only_goes_straight_to_sign_off(self):
		m = make_marisol()
		_close(m.open_deal)
		self.assertEqual(self._submitted(m)["status"], "Awaiting Sign-off")

	def test_apply_hold_returns_false_without_open_deals(self):
		m = make_marisol()
		_close(m.open_deal)
		name = self._submitted(m)["name"]
		self.assertFalse(apply_hold(frappe.get_doc("CRM Erasure Request", name)))

	def test_empty_request_cannot_submit(self):
		with self.assertRaises(frappe.ValidationError):
			submit_request(log_request())

	def test_nothing_confirmed_and_all_identifiers_excluded_cannot_submit(self):
		m = make_marisol()
		name = log_request("Contact", m.contact)
		doc = frappe.get_doc("CRM Erasure Request", name)
		for row in doc.identifiers:
			row.excluded = 1
		for row in doc.matches:
			row.confirmed = 0
		doc.save()
		with self.assertRaises(frappe.ValidationError):
			submit_request(name)

	def test_non_compliance_logger_can_submit_own_request(self):
		logger = make_user("logger@example.com", ["Sales User"]).name
		m = make_marisol(owner=logger)
		frappe.set_user(logger)
		name = log_request("Contact", m.contact)
		out = submit_request(name)
		self.assertEqual(out["status"], "On Hold")
		self.assertEqual(frappe.db.get_value("CRM Erasure Request", name, "status"), "On Hold")

	def test_cannot_submit_someone_elses_logged_request(self):
		m = make_marisol()
		name = log_request("Contact", m.contact)
		other = make_user("other.sales@example.com", ["Sales User"]).name
		frappe.set_user(other)
		with self.assertRaises(frappe.PermissionError):
			submit_request(name)

	def test_cannot_submit_twice(self):
		m = make_marisol()
		name = self._submitted(m)["name"]
		with self.assertRaises(frappe.PermissionError):
			submit_request(name)

	def test_notify_inserts_notification_and_skips_when_empty(self):
		user = make_compliance_user()
		request = make_request(requester_name="Someone").name
		notify([], "nothing", request)
		notify([user], f"Reminder for {request}", request)
		rows = frappe.get_all(
			"CRM Notification",
			filters={"to_user": user, "type": "Privacy"},
			fields=[
				"from_user",
				"notification_text",
				"message",
				"notification_type_doctype",
				"notification_type_doc",
				"reference_doctype",
				"reference_name",
			],
		)
		self.assertEqual(len(rows), 1)
		row = rows[0]
		self.assertEqual(row.from_user, "Administrator")
		self.assertEqual(row.notification_text, f"Reminder for {request}")
		self.assertEqual(row.notification_type_doctype, "CRM Erasure Request")
		self.assertEqual(row.notification_type_doc, request)
		self.assertEqual(row.reference_doctype, "CRM Erasure Request")
		self.assertEqual(row.reference_name, request)
