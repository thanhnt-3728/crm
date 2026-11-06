# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from crm.fcrm.doctype.crm_erasure_request import erasure_form_save_rules as rules
from crm.fcrm.doctype.crm_erasure_request import erasure_request_lifecycle as lifecycle
from crm.fcrm.doctype.crm_erasure_request.erasure_deadlines import load_erasure_holidays
from crm.fcrm.doctype.crm_erasure_request.erasure_guards import assert_can_decide, stored_requester
from crm.fcrm.doctype.crm_erasure_request.erasure_request_rows import (
	apply_exclusions,
	clean_identifier_rows,
	clean_match_rows,
)
from crm.fcrm.doctype.crm_erasure_request.erasure_states import (
	DECIDER,
	DRAFT,
	HOLD_STATES,
	ON_HOLD,
	PENDING_APPROVAL,
	PRIVACY_OFFICER,
	PRIVACY_OFFICER_ROLE,
	REQUESTER,
	transition_actor,
)

TRANSITION_FLAG = "erasure_transition"
ALLOWED_FLAG = "erasure_allowed"


class CRMErasureRequest(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		from crm.fcrm.doctype.crm_erasure_identifier.crm_erasure_identifier import CRMErasureIdentifier
		from crm.fcrm.doctype.crm_erasure_match.crm_erasure_match import CRMErasureMatch

		ack_due: DF.Date | None
		acknowledged_on: DF.Date | None
		approved_on: DF.Datetime | None
		approver: DF.Link | None
		executed_on: DF.Datetime | None
		hold_reason: DF.SmallText | None
		identifiers: DF.Table[CRMErasureIdentifier]
		known_limitations: DF.SmallText | None
		last_error: DF.SmallText | None
		matches: DF.Table[CRMErasureMatch]
		naming_series: DF.Literal["CRM-ERQ-.YYYY.-"]
		outcome: DF.JSON | None
		received_on: DF.Date
		rejection_reason: DF.SmallText | None
		requested_by: DF.Link | None
		response_due: DF.Date | None
		source_docname: DF.Data
		source_doctype: DF.Literal["CRM Lead", "CRM Deal", "Contact"]
		status: DF.Literal[
			"Draft", "Pending Approval", "On Hold", "Approved", "Executed", "Closed", "Rejected"
		]
		subject_name: DF.Data
	# end: auto-generated types

	def validate(self):
		user, before = frappe.session.user, None
		if self.is_new():
			rules.check_new_request(self)
			rules.strip_client_normalized(self, None)
			rules.check_source(self, user)
			self.status = self.status or DRAFT
			self.requested_by = user
		else:
			before = self.get_doc_before_save()
			if self.flags.get(TRANSITION_FLAG):
				rules.check_internal_save(self, before, self.flags.get(ALLOWED_FLAG) or set())
			else:
				rules.strip_client_normalized(self, before)
				rules.check_form_save(self, before, user)  # source and identifiers are fixed after insert
			# identity fields the two-person rule relies on never change after insert
			self.requested_by = before.requested_by
			self.owner = before.owner
		rules.check_dates(self)
		if lifecycle.due_dates_changed(self, before):
			lifecycle.set_due_dates(self, load_erasure_holidays())

	def on_trash(self):
		lifecycle.assert_deletable(self)

	def after_delete(self):
		lifecycle.forget_personal_data(self)

	def transition_to(self, status: str, **fields):
		"""The only way to change `status`: checks the move is legal and the session user may make it.

		`fields` may set only SYSTEM_FIELDS; unsaved edits to anything else make the save throw.
		Saves with ignore_permissions: the actor checks below are the permission.
		"""
		self._assert_saved()
		rules.assert_system_fields(fields)
		actor = transition_actor(self.status, status)
		if not actor:
			frappe.throw(
				_("Erasure request {0} cannot move from {1} to {2}").format(
					self.name, _(self.status), _(status)
				)
			)
		self._assert_actor(actor)
		self.update(fields)
		self.status = status
		self._save_internal({"status", *fields})

	def save_system_fields(self, **fields):
		"""Write SYSTEM_FIELDS (e.g. last_error, hold_reason) without changing status"""
		self._assert_saved()
		rules.assert_system_fields(fields)
		self.update(fields)
		self._save_internal(set(fields))

	def submit_for_approval(self):
		"""Draft -> Pending Approval, or On Hold when her open deals block it (hold rule F7)"""
		from crm.fcrm.doctype.crm_erasure_request.erasure_hold import blocking_open_deals, format_hold_reason

		self._assert_saved()
		lifecycle.assert_identifier_on_source(self)
		deals = blocking_open_deals(self)
		if deals:
			self.transition_to(ON_HOLD, hold_reason=format_hold_reason(deals))
		else:
			self.transition_to(PENDING_APPROVAL, hold_reason=None)

	def replace_matches(self, rows: list[dict]):
		"""Replace `matches` (discovery output). Draft: the requester; Pending/On Hold: a decider."""
		self._assert_match_editor()
		stored = [(row.ref_doctype, row.ref_name) for row in self.matches]
		self.set("matches", clean_match_rows(rows, stored))
		self._save_internal({"matches"})

	def set_match_exclusions(self, excluded: list[tuple[str, str]]):
		"""Mark exactly these (ref_doctype, ref_name) matches excluded and the rest included"""
		self._assert_match_editor()
		apply_exclusions(self.matches, excluded)
		self._save_internal({"matches"})

	def set_identifiers(self, rows: list[dict], region: str | None = None):
		"""Replace `identifiers`, normalizing each value here (any sent `normalized` is ignored)"""
		self._assert_saved()
		if self.status != DRAFT or frappe.session.user != stored_requester(self):
			frappe.throw(_("Only the requester can change identifiers of a Draft"), frappe.PermissionError)
		cleaned = clean_identifier_rows(rows, region)
		lifecycle.assert_identifier_on_source(self, cleaned)
		self.set("identifiers", cleaned)
		self._save_internal({"identifiers"})

	def apply_retention_rows(self, rows: list[dict], subject_name: str):
		"""Retention (`crm.erasure.retention`) on Close or Reject: store masked `rows` and `subject_name`
		as given; a Privacy Officer, in the same transaction as the transition"""
		from crm.fcrm.doctype.crm_erasure_request import erasure_retention_rows as retention

		self._assert_saved()
		retention.assert_can_apply_retention(self, subject_name)
		self.set("identifiers", retention.retained_identifier_rows(rows))
		self.subject_name = subject_name
		self._save_internal({"identifiers", "subject_name"})

	def _assert_saved(self):
		# a doc built with frappe.get_doc({...}) has no __islocal, so is_new() alone is not enough
		if self.is_new() or not self.name or not frappe.db.exists(self.doctype, self.name):
			frappe.throw(_("Save the erasure request as a Draft first"))

	def _assert_match_editor(self):
		self._assert_saved()
		if self.status == DRAFT:
			self._assert_actor(REQUESTER)
		elif self.status in HOLD_STATES:
			assert_can_decide(self)
		else:
			frappe.throw(_("Matches of {0} are final once it is approved").format(self.name))

	def _assert_actor(self, actor: str):
		user = frappe.session.user
		if actor == REQUESTER and user != stored_requester(self):
			frappe.throw(_("Only the requester can change {0}").format(self.name), frappe.PermissionError)
		elif actor == DECIDER:
			assert_can_decide(self)
		elif actor == PRIVACY_OFFICER and PRIVACY_OFFICER_ROLE not in frappe.get_roles(user):
			frappe.throw(_("Only a Privacy Officer can close {0}").format(self.name), frappe.PermissionError)

	def _save_internal(self, allowed: set[str]):
		self.flags[TRANSITION_FLAG], self.flags[ALLOWED_FLAG] = True, allowed
		try:
			self.save(ignore_permissions=True)
		finally:
			self.flags[TRANSITION_FLAG], self.flags[ALLOWED_FLAG] = False, None
