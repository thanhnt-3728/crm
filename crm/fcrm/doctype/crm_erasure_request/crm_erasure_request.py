# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate, now_datetime

from crm.privacy.deadlines import acknowledge_by, respond_by

FULL_ACCESS_ROLES = {"Compliance", "Sales Manager"}
CRM_ROLES = {"Sales User", "Sales Manager", "Compliance"}
LOGGER_VISIBLE_STATUS = "Logged"

# Moved only by the privacy system (see `crm.privacy.system_write`), never by a user write.
PROTECTED_FIELDS = (
	"status",
	"logged_by",
	"approved_by",
	"approved_on",
	"erased_on",
	"erasure_error",
	"delete_after",
	"acknowledge_by",
	"respond_by",
	"ack_reminder_sent",
	"day30_reminder_sent",
	"day40_alert_sent",
)


class CRMErasureRequest(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		from crm.fcrm.doctype.crm_erasure_checklist_item.crm_erasure_checklist_item import (
			CRMErasureChecklistItem,
		)
		from crm.fcrm.doctype.crm_erasure_identifier.crm_erasure_identifier import CRMErasureIdentifier
		from crm.fcrm.doctype.crm_erasure_match.crm_erasure_match import CRMErasureMatch

		ack_reminder_sent: DF.Check
		acknowledge_by: DF.Date | None
		acknowledged_on: DF.Date | None
		acknowledgment_sent: DF.Check
		answered_on: DF.Date | None
		approved_by: DF.Link | None
		approved_on: DF.Datetime | None
		channel: DF.Literal["Email", "Phone", "Web form", "Mail", "Other"]
		checklist: DF.Table[CRMErasureChecklistItem]
		contract_references: DF.SmallText | None
		day30_reminder_sent: DF.Check
		day40_alert_sent: DF.Check
		delete_after: DF.Date | None
		denial_reason: DF.SmallText | None
		erased_on: DF.Datetime | None
		erasure_error: DF.SmallText | None
		identifiers: DF.Table[CRMErasureIdentifier]
		logged_by: DF.Link | None
		matches: DF.Table[CRMErasureMatch]
		original_message: DF.LongText | None
		outcome: DF.Literal["", "Completed", "Partly completed", "Denied"]
		received_on: DF.Date
		request_type: DF.Literal["Erasure"]
		requester_names: DF.SmallText | None
		respond_by: DF.Date | None
		status: DF.Literal[
			"Logged", "Awaiting Sign-off", "On Hold", "Erasing", "Erased", "Declined", "Closed"
		]
	# end: auto-generated types

	def before_insert(self):
		# Always the real session user: the approval rule ("not the logger") depends on it.
		self.logged_by = frappe.session.user

	def validate(self):
		self.reject_protected_field_changes()
		self.set_deadlines()
		self.guard_and_stamp_checklist()
		self.validate_status_rules()

	def reject_protected_field_changes(self):
		if self.is_new() or frappe.flags.privacy_system_write:
			return
		for fieldname in PROTECTED_FIELDS:
			if self.has_value_changed(fieldname):
				frappe.throw(
					_("{0} can only be changed by the system.").format(self.meta.get_label(fieldname))
				)

	def set_deadlines(self):
		received = getdate(self.received_on)
		self.acknowledge_by = acknowledge_by(received)
		self.respond_by = respond_by(received)

	def validate_status_rules(self):
		if self.status == "Declined" and not self.denial_reason:
			frappe.throw(_("A denial reason is required to decline a request."))

		if self.status == "Closed":
			if not self.answered_on:
				frappe.throw(_("Date answered is required to close a request."))
			if not self.outcome:
				frappe.throw(_("An outcome is required to close a request."))
			if self.outcome == "Denied" and not self.denial_reason:
				frappe.throw(_("A denial reason is required when the outcome is Denied."))
			if any(not row.done for row in self.checklist):
				frappe.throw(_("Every checklist item must be done before the request can be closed."))

	def guard_and_stamp_checklist(self):
		before = self.get_doc_before_save()
		old_rows = {row.name: row for row in (before.checklist if before else []) if row.name}

		if not frappe.flags.in_erasure_job and self._checklist_changed(old_rows):
			if "Compliance" not in frappe.get_roles():
				frappe.throw(_("Only Compliance can change the checklist."), frappe.PermissionError)

		for row in self.checklist:
			old = old_rows.get(row.name) if row.name else None
			if not row.done:
				row.done_by = None
				row.done_on = None
			elif old and old.done:
				# Already ticked: keep the original stamp.
				row.done_by = old.done_by
				row.done_on = old.done_on
			else:
				row.done_by = frappe.session.user
				row.done_on = now_datetime()

	def _checklist_changed(self, old_rows) -> bool:
		current = {row.name: row for row in self.checklist if row.name in old_rows}
		if len(current) != len(self.checklist) or len(current) != len(old_rows):
			return True  # a row was added or removed
		return any(
			(row.description, bool(row.done), bool(row.auto_added))
			!= (old_rows[name].description, bool(old_rows[name].done), bool(old_rows[name].auto_added))
			for name, row in current.items()
		)

	def can_approve(self, user: str) -> bool:
		"""Approval needs the Compliance role and a different person than the logger."""
		return "Compliance" in frappe.get_roles(user) and user != self.logged_by


def has_permission(doc, ptype=None, user=None):
	user = user or frappe.session.user
	roles = set(frappe.get_roles(user))

	if roles & FULL_ACCESS_ROLES:
		return True

	is_new = ptype == "create" or (hasattr(doc, "is_new") and doc.is_new())
	if is_new:
		# Any CRM user can log a request (spec 5.3).
		return bool(roles & CRM_ROLES)

	# The logger only sees their own request while it is still being put together.
	return doc.get("logged_by") == user and doc.get("status") == LOGGER_VISIBLE_STATUS


def get_permission_query_conditions(user=None):
	user = user or frappe.session.user

	if user == "Administrator" or set(frappe.get_roles(user)) & FULL_ACCESS_ROLES:
		return ""

	table = "`tabCRM Erasure Request`"
	return (
		f"({table}.`logged_by` = {frappe.db.escape(user)} "
		f"and {table}.`status` = {frappe.db.escape(LOGGER_VISIBLE_STATUS)})"
	)
