# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""CRM Erasure Request (design 5.2, 5.4).

The controller is the real gate for server-owned data: whatever the endpoint (`frappe.client.save`,
`set_value`, `insert`), `validate` refuses a change to the status, the approval and job fields, the
reminder flags and every child row unless it is made inside `server_write()` (see
`crm.privacy.request_status`). Phases 03, 05 and 06 reach those fields only through that block.
"""

import frappe
from frappe import _
from frappe.model import no_value_fields
from frappe.model.document import Document
from frappe.utils import cint, get_datetime, getdate, today

from crm.privacy import business_days
from crm.privacy.request_status import (
	FINISHED_STATUSES,
	INITIAL_STATUS,
	assert_not_frozen,
	assert_transition,
	is_frozen_ok,
	is_server_write,
)
from crm.privacy.request_visibility import INTERNAL_FIELDS

CHILD_TABLES = ("identifiers", "matches", "checklist", "contract_references")
SERVER_OWNED_FIELDS = (
	"status",
	"logged_by",
	"approver",
	"approved_on",
	"erased_on",
	"erasure_job_status",
	"erasure_error",
	"approved_plan_hash",
	"erasure_queued_at",
	"erasure_started_at",
	"pending_file_deletions",
	"ack_reminder_sent",
	"day30_reminder_sent",
	"day40_alert_sent",
	"acknowledgment_sent",
	"acknowledged_on",
	"closed_on",
	"purge_after",
	"outcome",
	"date_answered",
	"denial_reason",
)


def _normalize(df, value):
	"""A value in a form that is equal whether it came from the database or from a JSON payload."""
	if df.fieldtype in ("Check", "Int"):
		return cint(value)
	if value in (None, ""):
		return None
	if df.fieldtype == "Datetime":
		return get_datetime(value)
	if df.fieldtype == "Date":
		return getdate(value)
	return str(value)


def _row_signature(doc, table: str) -> list[tuple]:
	child_meta = frappe.get_meta(doc.meta.get_field(table).options)
	fields = [df for df in child_meta.fields if df.fieldtype not in no_value_fields]
	return [tuple(_normalize(df, row.get(df.fieldname)) for df in fields) for row in doc.get(table) or []]


class CRMErasureRequest(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		from crm.fcrm.doctype.crm_erasure_checklist_item.crm_erasure_checklist_item import (
			CRMErasureChecklistItem,
		)
		from crm.fcrm.doctype.crm_erasure_contract_reference.crm_erasure_contract_reference import (
			CRMErasureContractReference,
		)
		from crm.fcrm.doctype.crm_erasure_identifier.crm_erasure_identifier import CRMErasureIdentifier
		from crm.fcrm.doctype.crm_erasure_match.crm_erasure_match import CRMErasureMatch

		ack_reminder_sent: DF.Check
		acknowledge_by: DF.Date | None
		acknowledged_on: DF.Date | None
		acknowledgment_sent: DF.Check
		approved_on: DF.Datetime | None
		approved_plan_hash: DF.Data | None
		approver: DF.Link | None
		channel: DF.Literal["Email", "Phone", "Web form", "Mail", "Other"]
		checklist: DF.Table[CRMErasureChecklistItem]
		closed_on: DF.Date | None
		contract_references: DF.Table[CRMErasureContractReference]
		date_answered: DF.Date | None
		date_received: DF.Date
		day30_reminder_sent: DF.Check
		day40_alert_sent: DF.Check
		denial_reason: DF.Text | None
		erased_on: DF.Datetime | None
		erasure_error: DF.SmallText | None
		erasure_job_status: DF.Literal["", "Queued", "Running", "Failed"]
		erasure_queued_at: DF.Datetime | None
		erasure_started_at: DF.Datetime | None
		identifiers: DF.Table[CRMErasureIdentifier]
		logged_by: DF.Link | None
		matches: DF.Table[CRMErasureMatch]
		naming_series: DF.Literal["PDR-.####"]
		original_message: DF.Text | None
		outcome: DF.Literal["", "Completed", "Partly completed", "Denied"]
		pending_file_deletions: DF.LongText | None
		purge_after: DF.Date | None
		request_type: DF.Literal["Erasure"]
		requester_names: DF.SmallText | None
		respond_by: DF.Date | None
		status: DF.Literal["Logged", "Awaiting sign-off", "On Hold", "Erased", "Declined", "Closed"]
	# end: auto-generated types

	def before_insert(self):
		# Whatever a generic insert carried, the logger is the session user (RT-3).
		self.logged_by = frappe.session.user

	def _validate_links(self):
		# Match rows may point at a record that was deleted since (CRM Erasure Match is in
		# `ignore_links_on_delete`), and Frappe re-checks every child link before `validate` on every save. So the
		# server's own writes skip the check; a generic save keeps it, with the guard below on top.
		if not is_server_write():
			super()._validate_links()

	def validate_higher_perm_levels(self):
		# The internal fields sit at a permlevel nobody can write, and Frappe would quietly reset them here. Refuse the
		# attempt first, like every other server-owned field (RT-3).
		if not is_server_write():
			self.assert_server_owned_unchanged(self.get_latest(), INTERNAL_FIELDS, ())
		super().validate_higher_perm_levels()

	def validate(self):
		before = self.get_latest()  # None on insert
		if before and not is_frozen_ok():
			assert_not_frozen(before.erasure_job_status)
		if not is_server_write():
			if before and before.status in FINISHED_STATUSES:
				self.assert_finished_request_unchanged(before)
			self.assert_server_owned_unchanged(before)
		self.request_type = "Erasure"
		self.validate_date_received()
		self.set_deadlines()
		self.validate_status(before)

	def validate_date_received(self):
		if self.date_received and getdate(self.date_received) > getdate(today()):
			frappe.throw(_("Date received cannot be in the future"))

	def set_deadlines(self):
		if self.date_received:
			received = getdate(self.date_received)
			self.acknowledge_by = business_days.acknowledge_by(received)
			self.respond_by = business_days.respond_by(received)

	def validate_status(self, before):
		if before is None:
			if (self.status or INITIAL_STATUS) != INITIAL_STATUS:
				frappe.throw(_("A request starts as {0}").format(INITIAL_STATUS))
		elif self.status != before.status:
			assert_transition(before.status, self.status, self.denial_reason)

	def assert_finished_request_unchanged(self, before):
		"""An Erased, Declined or Closed request is the compliance record: no field or row changes unless
		the server writes it (checklist ticks, close, wipe)."""
		changed = any(
			_normalize(df, self.get(df.fieldname)) != _normalize(df, before.get(df.fieldname))
			for df in self.meta.fields
			if df.fieldtype not in no_value_fields
		) or any(_row_signature(self, table) != _row_signature(before, table) for table in CHILD_TABLES)
		if changed:
			frappe.throw(_("A request that is {0} can no longer be changed").format(_(before.status)))

	def assert_server_owned_unchanged(self, before, fields=SERVER_OWNED_FIELDS, tables=CHILD_TABLES):
		"""Refuse a change to a server-owned field or child row made outside `server_write()` (RT-3)."""
		for fieldname in fields:
			df = self.meta.get_field(fieldname)
			# On insert `logged_by` is overwritten and `status` is checked as the initial status.
			if before is None and fieldname in ("logged_by", "status"):
				continue
			old = _normalize(df, before.get(fieldname)) if before else _normalize(df, df.default)
			if _normalize(df, self.get(fieldname)) != old:
				frappe.throw(_("{0} cannot be changed directly").format(_(df.label)), frappe.ValidationError)
		for table in tables:
			old_rows = _row_signature(before, table) if before else []
			if _row_signature(self, table) != old_rows:
				frappe.throw(_("{0} cannot be changed directly").format(_(self.meta.get_field(table).label)))
