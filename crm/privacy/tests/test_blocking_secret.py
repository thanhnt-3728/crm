# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""A missing do-not-contact secret (RT-15): manual saves fail closed, automatic paths fail soft (V1)."""

import frappe

from crm.api.whatsapp import validate as validate_whatsapp_message
from crm.privacy.do_not_contact import (
	ErasedPersonBlockedError,
	PrivacySettingsIncompleteError,
	skip_blocked,
)
from crm.privacy.tests.automatic_path_fixtures import facebook_source, incoming_whatsapp_message, meta_lead
from crm.privacy.tests.make_test_user import (
	RequestTestCase,
	block,
	forget_dnc_secret,
	make_contact,
	make_lead,
	purge_logs_titled,
)

EMAIL, PHONE = "marisol.vega@example.net", "+15305550123"
LEAD = "CRM Lead"
TITLE = "DNC secret unavailable"


class SecretMissingTestCase(RequestTestCase):
	def setUp(self):
		super().setUp()
		block(("email", EMAIL), ("phone", PHONE))
		forget_dnc_secret()

	def tearDown(self):
		frappe.db.rollback()
		purge_logs_titled(self._started, TITLE)
		super().tearDown()

	def notices(self) -> int:
		return frappe.db.count("CRM Notification", {"type": "Compliance", "to_user": self.compliance})

	def secret_logs(self) -> list:
		return frappe.get_all(
			"Error Log",
			{"method": ["like", f"{TITLE}%"], "creation": [">=", self._started]},
			["method", "error"],
		)

	def assertLoggedWithoutPersonalData(self, context: str):
		(log,) = self.secret_logs()
		self.assertEqual(log.method, f"{TITLE}: {context}")
		self.assertEqual(log.error, "DncSecretUnavailableError")


class TestManualSaveFailsClosed(SecretMissingTestCase):
	def test_a_lead_with_an_email_or_phone_is_refused_with_the_admin_message(self):
		for values in ({"email": "anyone@example.net"}, {"mobile_no": "+15305550999"}):
			with self.assertRaises(PrivacySettingsIncompleteError) as caught:
				make_lead(**values)
			self.assertEqual(
				str(caught.exception), "Privacy settings are incomplete. Ask your administrator."
			)
			del frappe.local.message_log[:]

	def test_a_contact_is_refused_too(self):
		with self.assertRaises(PrivacySettingsIncompleteError):
			make_contact("Anyone", emails=["anyone@example.net"])

	def test_a_lead_with_no_email_or_phone_has_nothing_to_check(self):
		self.assertTrue(frappe.db.exists(LEAD, make_lead()))


class TestWhatsAppFailsSoft(SecretMissingTestCase):
	def test_the_message_is_saved_without_a_lead_and_compliance_is_told_once_a_day(self):
		first, second = incoming_whatsapp_message("+15305550991"), incoming_whatsapp_message("+15305550992")

		validate_whatsapp_message(first, None)
		validate_whatsapp_message(second, None)

		self.assertFalse(first.reference_docname or second.reference_docname)
		self.assertFalse(frappe.db.exists(LEAD, {"mobile_no": ["in", ["+15305550991", "+15305550992"]]}))
		self.assertEqual(frappe.local.message_log, [])
		self.assertEqual(self.notices(), 1)
		self.assertEqual(len(self.secret_logs()), 2)
		self.assertTrue(all(log.error == "DncSecretUnavailableError" for log in self.secret_logs()))
		self.assertEqual({log.method for log in self.secret_logs()}, {f"{TITLE}: WhatsApp lead creation"})


class TestFacebookFailsSoft(SecretMissingTestCase):
	def test_the_lead_is_kept_for_a_retry_with_its_id_only(self):
		source = facebook_source()
		logs_before = frappe.db.count("Failed Lead Sync Log")

		source.sync_single_lead(meta_lead("fb-9", "anyone@example.net"))

		self.assertFalse(frappe.db.exists(LEAD, {"facebook_lead_id": "fb-9"}))
		self.assertEqual(frappe.db.count("Failed Lead Sync Log"), logs_before + 1)
		self.assertEqual(frappe.local.message_log, [])
		self.assertEqual(self.notices(), 1)
		self.assertLoggedWithoutPersonalData("Facebook lead sync")


class TestWrongEncryptionKey(SecretMissingTestCase):
	"""A restore with another `encryption_key`: the row is there but cannot be decrypted, and Frappe raises its
	own message (L4) on the way to answering "no secret"."""

	def setUp(self):
		super().setUp()
		frappe.db.sql(
			"insert into `__Auth` (doctype, name, fieldname, password, encrypted) values (%s, %s, %s, %s, 1)",
			("CRM Privacy Settings", "CRM Privacy Settings", "dnc_hash_secret", "not-a-valid-token"),
		)

	def test_whatsapp_keeps_the_message_without_a_lead_and_without_a_dialog(self):
		message = incoming_whatsapp_message("+15305550993")

		validate_whatsapp_message(message, None)

		self.assertFalse(message.reference_docname)
		self.assertFalse(frappe.db.exists(LEAD, {"mobile_no": "+15305550993"}))
		self.assertEqual(frappe.local.message_log, [])
		self.assertLoggedWithoutPersonalData("WhatsApp lead creation")


class TestSkipBlocked(SecretMissingTestCase):
	def test_every_message_queued_inside_the_block_is_dropped_and_earlier_ones_stay(self):
		frappe.msgprint("earlier", alert=False)
		earlier = len(frappe.local.message_log)

		with skip_blocked("test") as skip:
			frappe.msgprint("noise one")
			frappe.msgprint("noise two")
			frappe.throw("blocked", ErasedPersonBlockedError)

		self.assertTrue(skip.skipped)
		self.assertEqual(len(frappe.local.message_log), earlier)
		del frappe.local.message_log[:]

	def test_other_errors_pass_through(self):
		with self.assertRaises(KeyError), skip_blocked("test"):
			raise KeyError("not ours")

	def test_a_clean_block_does_not_skip(self):
		with skip_blocked("test") as skip:
			pass
		self.assertFalse(skip.skipped)
