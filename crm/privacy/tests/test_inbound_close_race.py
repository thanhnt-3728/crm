# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Fix round 1 (M1): mail that arrives while a close is running must not land on the request it just closed.

Close holds the request row lock until it commits. Routing takes the same lock and re-reads the status under it, so
it waits for the close and then sees Closed."""

from unittest.mock import patch

import frappe

from crm.privacy.tests.inbound_helpers import EMAIL, LEAD, REQUEST, InboundTestCase
from crm.privacy.tests.make_test_user import force_request, make_request


class TestRoutingRechecksUnderTheLock(InboundTestCase):
	def setUp(self):
		super().setUp()
		self.request = make_request(self.logger)
		force_request(self.request, status="Erased")

	def test_routing_reads_the_request_status_with_the_row_lock(self):
		locked = []
		real = frappe.db.get_value

		def spy(doctype, filters=None, *args, **kwargs):
			if doctype == REQUEST and filters == self.request and kwargs.get("for_update"):
				locked.append(args or kwargs.get("fieldname"))
			return real(doctype, filters, *args, **kwargs)

		with patch.object(frappe.db, "get_value", side_effect=spy):
			self.receive()
		self.assertTrue(locked)

	def test_a_close_that_commits_between_the_lookup_and_the_lock_wins(self):
		real = frappe.db.get_value

		def close_first(doctype, filters=None, *args, **kwargs):
			if doctype == REQUEST and filters == self.request and kwargs.get("for_update"):
				force_request(self.request, status="Closed")  # the close committed while routing waited
			return real(doctype, filters, *args, **kwargs)

		with patch.object(frappe.db, "get_value", side_effect=close_first):
			doc = self.receive()
		self.assertNotEqual(self.reference(doc), (REQUEST, self.request))
		frappe.db.delete(LEAD, {"email": EMAIL})

	def test_an_open_request_still_takes_the_mail(self):
		doc = self.receive()
		self.assertEqual(self.reference(doc), (REQUEST, self.request))
