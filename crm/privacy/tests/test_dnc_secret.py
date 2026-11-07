# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""The do-not-contact HMAC key: created once, never lost on a settings save, never regenerated."""

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils.password import get_decrypted_password

from crm.fcrm.doctype.crm_privacy_settings.crm_privacy_settings import (
	DncSecretUnavailableError,
	get_dnc_secret,
)
from crm.privacy.install import setup
from crm.privacy.tests.make_test_user import make_user

SETTINGS = "CRM Privacy Settings"
GUARD = "crm.fcrm.doctype.crm_privacy_settings.crm_privacy_settings"


def _forget_secret():
	frappe.db.delete("__Auth", {"doctype": SETTINGS, "fieldname": "dnc_hash_secret"})


def _api_save_as(user: str, **overrides):
	"""The form/API path: load the doc, change fields, save it through frappe.client.save."""
	frappe.set_user(user)
	try:
		payload = frappe.get_single(SETTINGS).as_dict()
		payload.update(overrides)
		frappe.client.save(payload)
	finally:
		frappe.set_user("Administrator")


class TestDncSecret(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		setup()

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def test_setup_generates_a_hex_secret(self):
		secret = get_dnc_secret()
		self.assertEqual(len(secret), 64)
		int(secret, 16)

	def test_secret_is_a_hidden_read_only_password_field_for_system_manager_only(self):
		meta = frappe.get_meta(SETTINGS)
		field = meta.get_field("dnc_hash_secret")
		self.assertEqual(field.fieldtype, "Password")
		self.assertTrue(field.hidden)
		self.assertTrue(field.read_only)
		self.assertEqual(field.permlevel, 1)
		self.assertEqual(
			{p.role for p in meta.permissions if p.permlevel == 1 and p.read}, {"System Manager"}
		)

	def test_non_system_manager_cannot_read_the_secret(self):
		secret = get_dnc_secret()
		user = make_user("sales.reader@example.com", roles=["Sales User"])
		frappe.set_user(user)
		try:
			with self.assertRaises(frappe.PermissionError):
				frappe.client.get(SETTINGS)
			with self.assertRaises(frappe.PermissionError):
				frappe.client.get_password(SETTINGS, SETTINGS, "dnc_hash_secret")
			with self.assertRaises(frappe.PermissionError):
				frappe.get_doc(SETTINGS).check_permission("read")
		finally:
			frappe.set_user("Administrator")
		self.assertNotIn(secret, str(frappe.get_doc(SETTINGS).as_dict()))

	def test_secret_is_stable_across_setup_runs(self):
		before = get_dnc_secret()
		setup()
		setup()
		self.assertEqual(get_dnc_secret(), before)

	def test_missing_secret_is_generated_when_there_is_nothing_to_orphan(self):
		_forget_secret()
		self.assertEqual(len(get_dnc_secret()), 64)

	def test_missing_secret_is_not_regenerated_when_blocks_exist(self):
		_forget_secret()
		with patch("frappe.db.table_exists", return_value=True), patch("frappe.db.count", return_value=3):
			with self.assertRaises(DncSecretUnavailableError):
				get_dnc_secret()
			setup()  # install and "Restore defaults" carry on without it (review L1)
		self.assertFalse(get_decrypted_password(SETTINGS, SETTINGS, "dnc_hash_secret", raise_exception=False))

	def test_error_message_points_to_a_backup_not_to_the_settings_form(self):
		_forget_secret()
		with (
			patch("frappe.db.table_exists", return_value=True),
			patch("frappe.db.count", return_value=3),
			self.assertRaises(DncSecretUnavailableError) as ctx,
		):
			get_dnc_secret()
		message = str(ctx.exception).lower()
		self.assertIn("backup", message)
		self.assertIn("encryption_key", message)
		self.assertIn("administrator", message)
		self.assertNotIn("in crm privacy settings", message)

	def test_generation_rereads_the_secret_after_taking_the_lock(self):
		# Another worker created the key while this one waited for the lock: use theirs, write nothing.
		with (
			patch(f"{GUARD}.get_decrypted_password", side_effect=[None, "c" * 64]),
			patch(f"{GUARD}.set_encrypted_password") as write,
			patch(f"{GUARD}._dnc_entries_exist", return_value=False),
			patch("frappe.db.get_value") as lock,
		):
			self.assertEqual(get_dnc_secret(), "c" * 64)
		write.assert_not_called()
		self.assertTrue(lock.call_args.kwargs.get("for_update"))

	def test_document_holds_a_masked_placeholder_once_the_secret_exists(self):
		_forget_secret()
		secret = get_dnc_secret()
		masked = frappe.db.get_single_value(SETTINGS, "dnc_hash_secret")
		self.assertTrue(masked)
		self.assertEqual(set(masked), {"*"})
		self.assertNotEqual(masked, secret)

	# C1: Frappe deletes a Password value on save when the field is empty on the document.
	def test_secret_survives_a_document_save(self):
		before = get_dnc_secret()
		doc = frappe.get_single(SETTINGS)
		doc.contract_retention_months = 24
		doc.save()
		self.assertEqual(get_dnc_secret(), before)
		self.assertEqual(frappe.get_single(SETTINGS).contract_retention_months, 24)

	def test_secret_survives_a_save_before_it_was_ever_read(self):
		_forget_secret()
		frappe.db.set_single_value(SETTINGS, "dnc_hash_secret", None)
		doc = frappe.get_single(SETTINGS)
		doc.save()
		first = get_dnc_secret()
		frappe.get_single(SETTINGS).save()
		self.assertEqual(get_dnc_secret(), first)

	def test_secret_survives_an_api_save_with_a_blank_or_masked_field(self):
		before = get_dnc_secret()
		manager = make_user("sysman.saver@example.com", roles=["System Manager"])
		for value in ("", None, "*" * 64, "*****"):
			with self.subTest(payload=value):
				_api_save_as(manager, dnc_hash_secret=value, contract_retention_months=12)
				self.assertEqual(get_dnc_secret(), before)

	def test_api_save_cannot_replace_the_secret(self):
		before = get_dnc_secret()
		manager = make_user("sysman.replacer@example.com", roles=["System Manager"])
		_api_save_as(manager, dnc_hash_secret="b" * 64)
		self.assertEqual(get_dnc_secret(), before)
