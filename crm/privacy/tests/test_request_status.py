# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Status machine and the server-write flag of CRM Erasure Request (design 5.2). No DB."""

import itertools

import frappe
from frappe.tests import UnitTestCase

from crm.privacy.request_status import (
	ALLOWED,
	FROZEN_JOB_STATUSES,
	INITIAL_STATUS,
	STATUSES,
	assert_not_frozen,
	assert_transition,
	is_allowed,
	is_frozen_ok,
	is_server_write,
	server_write,
)

LOGGED, AWAITING, HOLD, ERASED, DECLINED, CLOSED = (
	"Logged",
	"Awaiting sign-off",
	"On Hold",
	"Erased",
	"Declined",
	"Closed",
)

PERMITTED = {
	(LOGGED, AWAITING),
	(LOGGED, HOLD),
	(AWAITING, HOLD),
	(HOLD, AWAITING),
	(AWAITING, ERASED),
	(LOGGED, DECLINED),
	(AWAITING, DECLINED),
	(HOLD, DECLINED),
	(ERASED, CLOSED),
	(DECLINED, CLOSED),
}


class TestTransitionTable(UnitTestCase):
	def test_statuses_and_initial(self):
		self.assertEqual(set(STATUSES), {LOGGED, AWAITING, HOLD, ERASED, DECLINED, CLOSED})
		self.assertEqual(INITIAL_STATUS, LOGGED)

	def test_every_pair_matches_the_table(self):
		for old, new in itertools.product(STATUSES, STATUSES):
			expected = (old, new) in PERMITTED
			self.assertEqual(is_allowed(old, new), expected, f"{old} -> {new}")

	def test_table_has_no_extra_keys(self):
		self.assertEqual({(o, n) for o, targets in ALLOWED.items() for n in targets}, PERMITTED)

	def test_unknown_status_is_never_allowed(self):
		self.assertFalse(is_allowed("Bogus", LOGGED))
		self.assertFalse(is_allowed(LOGGED, "Bogus"))
		self.assertFalse(is_allowed(None, LOGGED))

	def test_disallowed_transition_throws(self):
		for old, new in itertools.product(STATUSES, STATUSES):
			if (old, new) in PERMITTED or new == DECLINED:
				continue
			with self.assertRaises(frappe.ValidationError, msg=f"{old} -> {new}"):
				assert_transition(old, new)

	def test_allowed_transition_does_not_throw(self):
		for old, new in PERMITTED - {(LOGGED, DECLINED), (AWAITING, DECLINED), (HOLD, DECLINED)}:
			assert_transition(old, new)

	def test_closed_is_terminal(self):
		for new in STATUSES:
			with self.assertRaises(frappe.ValidationError):
				assert_transition(CLOSED, new)

	def test_decline_needs_a_reason(self):
		for old in (LOGGED, AWAITING, HOLD):
			for reason in (None, "", "   "):
				with self.assertRaises(frappe.ValidationError, msg=f"{old} reason={reason!r}"):
					assert_transition(old, DECLINED, reason)
			assert_transition(old, DECLINED, "Identity not verifiable")

	def test_decline_from_a_finished_state_is_still_refused_even_with_a_reason(self):
		for old in (ERASED, DECLINED, CLOSED):
			with self.assertRaises(frappe.ValidationError):
				assert_transition(old, DECLINED, "Reason")


class TestFrozenGuard(UnitTestCase):
	def test_queued_and_running_are_frozen(self):
		self.assertEqual(set(FROZEN_JOB_STATUSES), {"Queued", "Running"})
		for status in ("Queued", "Running"):
			with self.assertRaises(frappe.ValidationError) as ctx:
				assert_not_frozen(status)
			self.assertIn("Erasure in progress", str(ctx.exception))

	def test_other_job_states_are_not_frozen(self):
		for status in (None, "", "Failed"):
			assert_not_frozen(status)


class TestServerWriteFlag(UnitTestCase):
	def test_off_by_default(self):
		self.assertFalse(is_server_write())
		self.assertFalse(is_frozen_ok())

	def test_on_inside_the_block_and_restored_after(self):
		with server_write():
			self.assertTrue(is_server_write())
			self.assertFalse(is_frozen_ok())
		self.assertFalse(is_server_write())

	def test_frozen_ok_is_opt_in(self):
		with server_write(frozen_ok=True):
			self.assertTrue(is_server_write())
			self.assertTrue(is_frozen_ok())
		self.assertFalse(is_frozen_ok())

	def test_restored_after_an_exception(self):
		with self.assertRaises(RuntimeError):
			with server_write(frozen_ok=True):
				raise RuntimeError("boom")
		self.assertFalse(is_server_write())
		self.assertFalse(is_frozen_ok())

	def test_nested_block_restores_the_outer_state(self):
		with server_write():
			with server_write(frozen_ok=True):
				self.assertTrue(is_frozen_ok())
			self.assertTrue(is_server_write())
			self.assertFalse(is_frozen_ok())
