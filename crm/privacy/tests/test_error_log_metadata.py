# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Error Logs the privacy code writes hold no personal data in their metadata or text (V1, M2): `frappe.log_error`
stores the web request's `form_dict` and a traceback, and a deal save or a webhook body carries the person's
email, phone or message."""

import json
from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from crm.privacy.do_not_contact import _send_email as send_privacy_notice
from crm.privacy.do_not_contact import report_secret_unavailable
from crm.privacy.notify import _send_email
from crm.privacy.on_hold import _isolated
from crm.privacy.retention import report_abandoned_safely
from crm.privacy.tests.make_test_user import purge_logs_titled

EMAIL = "m.vega@example.com"
TITLE = "ZZ-METADATA-"


class TestLogsFromAWebRequestHoldNoFormData(IntegrationTestCase):
	def setUp(self):
		self._started = frappe.utils.now_datetime()
		request = SimpleNamespace(method="POST", path="/api/method/x", referrer="")
		form = frappe._dict(email=EMAIL, contacts=[{"email": EMAIL}], message="hello Marisol")
		for name, value in (("request", request), ("form_dict", form)):
			patcher = patch.object(frappe.local, name, value, create=True)
			patcher.start()
			self.addCleanup(patcher.stop)
		self.addCleanup(self.restore)

	def restore(self):
		purge_logs_titled(self._started, TITLE)
		purge_logs_titled(self._started, "Privacy notice email")
		purge_logs_titled(self._started, "DNC secret unavailable: ZZ")
		frappe.db.commit()  # nosemgrep

	def logs(self, prefix: str) -> list:
		return frappe.get_all(
			"Error Log",
			{"method": ["like", f"{prefix}%"], "creation": [">=", self._started]},
			["method", "error", "metadata"],
		)

	def assert_clean(self, logs: list, error: str):
		self.assertEqual([log.error for log in logs], [error])
		for log in logs:
			self.assertNotIn(EMAIL, log.metadata or "")
			self.assertNotIn("Marisol", log.metadata or "")
			self.assertNotIn("form_dict", log.metadata or "")
			self.assertNotIn("Traceback", log.error)
			self.assertEqual(json.loads(log.metadata or "{}"), {})

	def test_a_failed_hook_logs_the_class_only_with_neutral_metadata(self):
		with _isolated(f"{TITLE}hook"):
			raise ConnectionError(EMAIL)
		self.assert_clean(self.logs(TITLE), "ConnectionError")

	def test_nothing_reaches_sentry_or_the_traceback_logger(self):
		with (
			patch.dict("os.environ", {"FRAPPE_SENTRY_DSN": "https://key@sentry.invalid/1"}),
			patch("frappe.utils.sentry.capture_exception") as sentry,
			patch("frappe.log_error") as log_error,
		):
			with _isolated(f"{TITLE}sentry"):
				raise RuntimeError(EMAIL)
		sentry.assert_not_called()
		log_error.assert_not_called()
		self.assertEqual([log.error for log in self.logs(TITLE)], ["RuntimeError"])

	def test_a_failed_notice_email_logs_the_class_only(self):
		with patch("frappe.sendmail", side_effect=OSError(EMAIL)):
			_send_email("a@example.com", "text", f"{TITLE}PDR")
		self.assert_clean(self.logs(TITLE), "OSError")

	def test_the_secret_missing_notice_holds_no_webhook_body(self):
		with patch("crm.privacy.do_not_contact.notify_compliance"):
			report_secret_unavailable("ZZ webhook")
		self.assert_clean(self.logs("DNC secret unavailable: ZZ"), "DncSecretUnavailableError")

	def test_a_failed_privacy_notice_email_logs_the_class_only(self):
		with patch("frappe.sendmail", side_effect=OSError(EMAIL)):
			send_privacy_notice("a@example.com", "text", None, None)
		self.assert_clean(self.logs("Privacy notice email"), "OSError")

	def test_a_failed_abandoned_file_report_logs_the_class_only(self):
		with patch("crm.privacy.retention.report_abandoned", side_effect=OSError(EMAIL)):
			report_abandoned_safely(f"{TITLE}PDR", [])
		self.assert_clean(self.logs(TITLE), "OSError")
