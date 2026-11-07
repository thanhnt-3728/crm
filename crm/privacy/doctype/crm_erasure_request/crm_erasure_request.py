# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import get_datetime, getdate, now_datetime, today

from crm.privacy.deadlines import acknowledge_by, respond_by
from crm.privacy.identifiers import normalize_identifier
from crm.privacy.permissions import is_compliance

# Only privacy service code may change these. Frappe does not enforce read_only
# server-side, so the controller does. Service code sets
# `doc.flags.privacy_system_write = True` after its own role and status checks.
PROTECTED_FIELDS = (
	"status",
	"approved_by",
	"approved_on",
	"erased_on",
	"erasure_status",
	"erasure_error",
	"decline_reason",
	"date_answered",
	"outcome",
	"denial_reason",
	"ack_reminder_sent",
	"day30_reminder_sent",
	"day40_alert_sent",
)

# Changes to these (and to the checklist table) need the Compliance role.
COMPLIANCE_FIELDS = ("contract_references", "acknowledgment_sent", "acknowledged_on")


class CRMErasureRequest(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		from crm.privacy.doctype.crm_erasure_checklist_item.crm_erasure_checklist_item import (
			CRMErasureChecklistItem,
		)
		from crm.privacy.doctype.crm_erasure_identifier.crm_erasure_identifier import CRMErasureIdentifier
		from crm.privacy.doctype.crm_erasure_match.crm_erasure_match import CRMErasureMatch

		ack_reminder_sent: DF.Check
		acknowledge_by: DF.Date | None
		acknowledged_on: DF.Date | None
		acknowledgment_sent: DF.Check
		approved_by: DF.Link | None
		approved_on: DF.Datetime | None
		arrived_via: DF.Literal["Email", "Phone", "Web form", "Mail", "Other"]
		checklist: DF.Table[CRMErasureChecklistItem]
		contract_references: DF.SmallText | None
		date_answered: DF.Date | None
		date_received: DF.Date
		day30_reminder_sent: DF.Check
		day40_alert_sent: DF.Check
		decline_reason: DF.SmallText | None
		denial_reason: DF.SmallText | None
		erased_on: DF.Datetime | None
		erasure_error: DF.SmallText | None
		erasure_status: DF.Literal["", "Queued", "Failed"]
		identifiers: DF.Table[CRMErasureIdentifier]
		logged_by: DF.Link | None
		matches: DF.Table[CRMErasureMatch]
		original_message: DF.Text | None
		other_names: DF.SmallText | None
		outcome: DF.Literal["", "Completed", "Partly completed", "Denied"]
		request_type: DF.Literal["Erasure"]
		requester_name: DF.Data | None
		respond_by: DF.Date | None
		status: DF.Literal["Logged", "Awaiting Sign-off", "On Hold", "Erased", "Declined", "Closed"]
	# end: auto-generated types

	def before_insert(self):
		self.logged_by = frappe.session.user

	def validate(self):
		self.enforce_write_rules()
		self.validate_date_received()
		self.set_deadlines()
		self.normalize_identifiers()
		self.stamp_checklist()

	def validate_date_received(self):
		if getdate(self.date_received) > getdate(today()):
			frappe.throw(_("Date received cannot be in the future"), frappe.ValidationError)

	def set_deadlines(self):
		received = getdate(self.date_received)
		self.acknowledge_by = acknowledge_by(received)
		self.respond_by = respond_by(received)

	def normalize_identifiers(self):
		seen = set()
		kept = []
		for row in self.identifiers:
			value = normalize_identifier(row.kind, row.value)
			if not value:
				frappe.throw(_("Not a valid email or phone"), frappe.ValidationError)
			row.value = value
			key = (row.kind, value)
			if key in seen:
				continue
			seen.add(key)
			kept.append(row)
		if len(kept) != len(self.identifiers):
			self.identifiers = kept
			for idx, row in enumerate(self.identifiers, start=1):
				row.idx = idx

	def _comparable(self, fieldname: str, value):
		"""Value in a form where an unset field and its saved empty value compare equal."""
		fieldtype = self.meta.get_field(fieldname).fieldtype
		if fieldtype == "Datetime":
			return get_datetime(value) if value else None
		if fieldtype == "Date":
			return getdate(value) if value else None
		if fieldtype == "Check":
			return int(value or 0)
		return value or ""

	def _changed(self, before, fieldname: str) -> bool:
		if before:
			previous = before.get(fieldname)
		else:
			# Insert: compare with the field's default (empty when it has none).
			previous = self.meta.get_field(fieldname).default
		return self._comparable(fieldname, self.get(fieldname)) != self._comparable(fieldname, previous)

	def _checklist_changed(self, before) -> bool:
		def snapshot(rows):
			return {row.name: (row.description, int(row.done or 0)) for row in rows}

		if not before:
			return bool(self.checklist)
		if len(self.checklist) != len(before.checklist):
			return True
		return snapshot(self.checklist) != snapshot(before.checklist)

	def enforce_write_rules(self):
		"""Reject changes the session user is not entitled to make.

		Protected fields are system-only; contract references, acknowledgment fields and
		the checklist are Compliance-only; `logged_by` never changes after insert.
		"""
		if self.flags.privacy_system_write:
			return
		before = self.get_doc_before_save()

		if before and self.logged_by != before.logged_by:
			frappe.throw(_("The logger of a request cannot be changed"), frappe.PermissionError)

		if any(self._changed(before, f) for f in PROTECTED_FIELDS):
			frappe.throw(_("These fields are managed by the system"), frappe.PermissionError)

		if not is_compliance():
			if any(self._changed(before, f) for f in COMPLIANCE_FIELDS) or self._checklist_changed(before):
				frappe.throw(
					_("Only Compliance can change the checklist, contract references or acknowledgment"),
					frappe.PermissionError,
				)

	def stamp_checklist(self):
		before = self.get_doc_before_save()
		previous = {row.name: row for row in before.checklist} if before else {}
		for row in self.checklist:
			prev = previous.get(row.name)
			if not row.done:
				row.done_by = None
				row.done_on = None
			elif prev and prev.done:
				# Already done: keep the original stamp, whatever the client sent.
				row.done_by = prev.done_by
				row.done_on = prev.done_on
			else:
				row.done_by = frappe.session.user
				row.done_on = now_datetime()
