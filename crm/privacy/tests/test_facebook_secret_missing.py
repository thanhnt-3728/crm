# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""While the do-not-contact secret is missing a Facebook lead is not consumed: it leaves a Failed Lead Sync Log
that holds the Meta lead id and nothing else, and a retry fetches the payload once the secret is back (M4, V1)."""

from unittest.mock import patch

import frappe

from crm.lead_syncing.doctype.lead_sync_source.facebook import FacebookSyncSource
from crm.privacy.do_not_contact import PrivacySettingsIncompleteError
from crm.privacy.tests.automatic_path_fixtures import facebook_source, meta_lead
from crm.privacy.tests.make_test_user import block
from crm.privacy.tests.test_blocking_secret import LEAD, SecretMissingTestCase

FACEBOOK = "crm.lead_syncing.doctype.lead_sync_source.facebook"
LOG = "Failed Lead Sync Log"
EMAIL_OF_LEAD = "anyone@example.net"
ERASED_EMAIL = "erased.later@example.net"


class TestFacebookLeadWaitsForTheSecret(SecretMissingTestCase):
	def held_logs(self, source) -> list:
		return frappe.get_all(LOG, {"source": source.source_name}, ["name", "type", "lead_data", "traceback"])

	def test_the_lead_leaves_a_retryable_log_with_the_id_only(self):
		source = facebook_source()

		result = source.sync_single_lead(meta_lead("fb-9", EMAIL_OF_LEAD))

		self.assertIsNone(result)
		self.assertFalse(frappe.db.exists(LEAD, {"facebook_lead_id": "fb-9"}))
		(log,) = self.held_logs(source)
		self.assertEqual(log.type, "Failure")
		self.assertEqual(frappe.parse_json(log.lead_data), {"id": "fb-9"})
		self.assertNotIn(EMAIL_OF_LEAD, f"{log.lead_data}{log.traceback}")
		self.assertNotIn("Marisol", f"{log.lead_data}{log.traceback}")
		self.assertNotIn("Traceback", log.traceback)
		self.assertEqual(source.skipped, 0)

	def test_the_same_lead_read_again_adds_no_second_log(self):
		source = facebook_source()

		source.sync_single_lead(meta_lead("fb-9", EMAIL_OF_LEAD))
		source.sync_single_lead(meta_lead("fb-9", EMAIL_OF_LEAD))

		self.assertEqual(len(self.held_logs(source)), 1)

	def test_the_retry_fetches_the_payload_and_imports_the_lead_once_the_secret_is_back(self):
		source = facebook_source()
		source.sync_single_lead(meta_lead("fb-9", EMAIL_OF_LEAD))
		(log,) = self.held_logs(source)

		with (
			patch(
				"crm.privacy.do_not_contact.get_dnc_secret", return_value="a-restored-secret-of-32-chars!!!"
			),
			patch(f"{FACEBOOK}.make_get_request", return_value=meta_lead("fb-9", EMAIL_OF_LEAD)) as request,
		):
			frappe.get_doc(LOG, log.name).retry_sync()

		self.assertTrue(frappe.db.exists(LEAD, {"facebook_lead_id": "fb-9", "email": EMAIL_OF_LEAD}))
		self.assertEqual(frappe.db.get_value(LOG, log.name, "type"), "Synced")
		self.assertIn("fb-9", request.call_args.args[0])

	def test_the_retry_creates_no_lead_for_a_person_on_the_list_once_the_secret_is_back(self):
		source = facebook_source()
		source.sync_single_lead(meta_lead("fb-7", ERASED_EMAIL))
		(log,) = self.held_logs(source)

		with (
			patch(
				"crm.privacy.do_not_contact.get_dnc_secret", return_value="a-restored-secret-of-32-chars!!!"
			),
			patch(f"{FACEBOOK}.make_get_request", return_value=meta_lead("fb-7", ERASED_EMAIL)),
		):
			block(("email", ERASED_EMAIL))  # her entry, under the restored key
			frappe.get_doc(LOG, log.name).retry_sync()

		self.assertFalse(frappe.db.exists(LEAD, {"facebook_lead_id": "fb-7"}))
		self.assertFalse(frappe.db.exists(LEAD, {"email": ERASED_EMAIL}))
		self.assertEqual(frappe.parse_json(frappe.db.get_value(LOG, log.name, "lead_data")), {"id": "fb-7"})

	def test_a_retry_with_the_secret_still_missing_raises_and_stays_failed(self):
		source = facebook_source()
		source.sync_single_lead(meta_lead("fb-9", EMAIL_OF_LEAD))
		(log,) = self.held_logs(source)

		with patch(f"{FACEBOOK}.make_get_request", return_value=meta_lead("fb-9", EMAIL_OF_LEAD)):
			with self.assertRaises(PrivacySettingsIncompleteError):
				frappe.get_doc(LOG, log.name).retry_sync()

		self.assertEqual(frappe.db.get_value(LOG, log.name, "type"), "Failure")
		self.assertEqual(len(self.held_logs(source)), 1)
		self.assertFalse(frappe.db.exists(LEAD, {"facebook_lead_id": "fb-9"}))

	def test_the_counter_belongs_to_the_instance(self):
		self.assertEqual(FacebookSyncSource("t", "f").skipped, 0)
		first, second = FacebookSyncSource("t", "f"), FacebookSyncSource("t", "f")
		first.skipped += 1
		self.assertEqual(second.skipped, 0)
		self.assertNotIn("skipped", FacebookSyncSource.__dict__)
