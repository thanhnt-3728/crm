# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Data pulled from records the logger cannot read stays hidden (RT-5, H1), and the mail count is bounded (M4)."""

import json
from unittest.mock import patch

from crm.api.erasure_requests import (
	get_identifier_impact,
	get_request,
	set_match_confirmed,
	suggest_matches,
)
from crm.privacy.tests.make_test_user import (
	RequestTestCase,
	as_user,
	make_lead,
	make_request,
	match_rows,
)
from crm.privacy.tests.test_matching_scope import LEAD, make_communication


class TestHiddenIdentifiersAndLimits(RequestTestCase):
	def setUp(self):
		super().setUp()
		self.name = make_request(self.logger, emails=["scoped@example.com"])

	def test_identifiers_pulled_from_a_hidden_lead_stay_hidden_from_the_logger(self):
		hidden = make_lead(
			owner=self.other, first_name="Hid", email="scoped@example.com", mobile_no="+15305559876"
		)
		as_user(self.compliance, suggest_matches, self.name)
		row = match_rows(self.name)[(LEAD, hidden)]
		as_user(self.compliance, set_match_confirmed, self.name, row.name, True)
		shown = as_user(self.logger, get_request, self.name)
		text = json.dumps(shown, default=str)
		self.assertNotIn(hidden, text)
		self.assertNotIn("+15305559876", text)
		self.assertEqual({i["value"] for i in shown["identifiers"]}, {"scoped@example.com"})
		full = as_user(self.compliance, get_request, self.name)
		self.assertIn("+15305559876", {i["value"] for i in full["identifiers"]})

	def test_identifiers_from_a_readable_record_are_still_shown_to_the_logger(self):
		readable = make_lead(
			owner=self.logger, first_name="Mine", email="scoped@example.com", mobile_no="+15305559877"
		)
		as_user(self.logger, suggest_matches, self.name)
		row = match_rows(self.name)[(LEAD, readable)]
		shown = as_user(self.logger, set_match_confirmed, self.name, row.name, True)
		self.assertIn("+15305559877", {i["value"] for i in shown["identifiers"]})

	def test_the_mail_count_stops_at_the_scan_limit_and_says_so(self):
		for _i in range(3):
			make_communication("scoped@example.com")
		with patch("crm.privacy.identifier_sync.COMMUNICATION_SCAN_LIMIT", 2):
			(row,) = as_user(self.compliance, get_identifier_impact, self.name)
		self.assertEqual((row["communications"], row["capped"]), (2, True))

	def test_a_mail_count_exactly_at_the_limit_is_not_capped(self):
		for _i in range(3):
			make_communication("scoped@example.com")
		with patch("crm.privacy.identifier_sync.COMMUNICATION_SCAN_LIMIT", 3):
			(row,) = as_user(self.compliance, get_identifier_impact, self.name)
		self.assertEqual((row["communications"], row["capped"]), (3, False))

	def test_the_logger_gets_no_cap_flag(self):
		(row,) = as_user(self.logger, get_identifier_impact, self.name)
		self.assertIsNone(row["capped"])
