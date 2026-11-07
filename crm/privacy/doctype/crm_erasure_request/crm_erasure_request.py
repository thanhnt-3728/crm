# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate, now_datetime, today

from crm.privacy.deadlines import acknowledge_by, respond_by
from crm.privacy.identifiers import normalize_identifier


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

	def stamp_checklist(self):
		before = self.get_doc_before_save()
		was_done = {row.name: row.done for row in before.checklist} if before else {}
		for row in self.checklist:
			if row.done and not was_done.get(row.name):
				row.done_by = frappe.session.user
				row.done_on = now_datetime()
			elif not row.done:
				row.done_by = None
				row.done_on = None
