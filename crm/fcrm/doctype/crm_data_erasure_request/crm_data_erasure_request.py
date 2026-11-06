# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import datetime
import json

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_days, getdate, now_datetime

from crm.fcrm.doctype.crm_data_erasure_request import erasure

PRIVACY_ROLE = "CRM Privacy Officer"

# CCPA: confirm receipt within 10 business days, respond within 45 calendar days.
ACKNOWLEDGE_BUSINESS_DAYS = 10
RESPOND_CALENDAR_DAYS = 45

LOCKED_FIELDS = (
	"status",
	"lead",
	"contact",
	"subject_name",
	"subject_email",
	"received_on",
	"received_via",
	"requested_by",
	"notes",
	"decided_by",
	"decided_on",
	"rejection_reason",
	"erasure_summary",
)


class CRMDataErasureRequest(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		acknowledge_by: DF.Date | None
		acknowledged_on: DF.Date | None
		contact: DF.Link | None
		decided_by: DF.Link | None
		decided_on: DF.Datetime | None
		erasure_summary: DF.Code | None
		lead: DF.Link | None
		naming_series: DF.Literal["CRM-DER-.YYYY.-"]
		notes: DF.SmallText | None
		received_on: DF.Date
		received_via: DF.Literal["Email", "Phone", "Web Form", "In Person", "Other"]
		rejection_reason: DF.SmallText | None
		requested_by: DF.Link | None
		respond_by: DF.Date | None
		status: DF.Literal["Pending Approval", "Rejected", "Completed"]
		subject_email: DF.Data | None
		subject_name: DF.Data | None
	# end: auto-generated types

	def before_insert(self):
		self.status = "Pending Approval"
		self.requested_by = frappe.session.user
		self.decided_by = self.decided_on = self.rejection_reason = self.erasure_summary = None

	def validate(self):
		if self.is_new():
			self.validate_subject()
			self.set_subject_details()
			self.validate_no_open_request()
		else:
			self.validate_locked_fields()

		if getdate(self.received_on) > getdate():
			frappe.throw(_("Received On cannot be in the future."))
		if self.acknowledged_on and getdate(self.acknowledged_on) < getdate(self.received_on):
			frappe.throw(_("Acknowledged On cannot be before Received On."))

		self.acknowledge_by = add_business_days(self.received_on, ACKNOWLEDGE_BUSINESS_DAYS)
		self.respond_by = add_days(self.received_on, RESPOND_CALENDAR_DAYS)

	def validate_locked_fields(self):
		"""After logging, only the acknowledgement date can be edited. Decisions go through
		approve_and_erase / reject, which write with db_set and skip this."""
		changed = [f for f in LOCKED_FIELDS if self.has_value_changed(f)]
		if changed:
			frappe.throw(
				_("{0} cannot be changed on an erasure request.").format(
					", ".join(_(self.meta.get_label(f)) for f in changed)
				)
			)

	def validate_subject(self):
		if not self.lead and not self.contact:
			frappe.throw(_("Pick the lead or contact the request is about."))
		# Whoever logs the request must be able to see the record it is about.
		if self.lead:
			frappe.has_permission("CRM Lead", doc=self.lead, throw=True)
		if self.contact:
			frappe.has_permission("Contact", doc=self.contact, throw=True)
		if self.lead and was_erased(self.lead):
			frappe.throw(_("Lead {0} has already been erased.").format(self.lead))

	def set_subject_details(self):
		if self.lead:
			lead = frappe.db.get_value("CRM Lead", self.lead, ["lead_name", "email"], as_dict=True)
			self.subject_name, self.subject_email = lead.lead_name, lead.email
		if self.contact:
			contact = frappe.db.get_value("Contact", self.contact, ["full_name", "email_id"], as_dict=True)
			self.subject_name = self.subject_name or contact.full_name
			self.subject_email = self.subject_email or contact.email_id

	def validate_no_open_request(self):
		for fieldname in ("lead", "contact"):
			value = self.get(fieldname)
			if not value:
				continue
			existing = frappe.db.get_value(
				"CRM Data Erasure Request", {fieldname: value, "status": "Pending Approval"}, "name"
			)
			if existing:
				frappe.throw(
					_("{0} already has an erasure request waiting for approval: {1}").format(
						_(self.meta.get_label(fieldname)), existing
					)
				)

	@frappe.whitelist()
	def get_preview(self) -> dict:
		"""What the erasure would touch, so the approver can check it before running it."""
		self.check_can_decide()
		return erasure.preview(self.resolve_subject())

	@frappe.whitelist()
	def approve_and_erase(self) -> dict:
		self.check_can_decide()
		subject = self.resolve_subject()
		summary = erasure.erase(subject, self.name)

		# db_set skips Version, which would otherwise keep the deleted contact's name.
		self.db_set(
			{
				"status": "Completed",
				"decided_by": frappe.session.user,
				"decided_on": now_datetime(),
				"contact": None,
				"erasure_summary": json.dumps(summary, indent=1, sort_keys=True),
			}
		)
		frappe.db.delete("Version", {"ref_doctype": self.doctype, "docname": self.name})
		return summary

	@frappe.whitelist()
	def reject(self, reason: str) -> None:
		self.check_can_decide()
		if not (reason or "").strip():
			frappe.throw(_("Give a reason for rejecting the request."))
		self.db_set(
			{
				"status": "Rejected",
				"decided_by": frappe.session.user,
				"decided_on": now_datetime(),
				"rejection_reason": reason.strip(),
			}
		)

	def check_can_decide(self):
		check_can_decide(self, frappe.session.user, frappe.get_roles())

	def resolve_subject(self) -> erasure.Subject:
		if self.lead and not frappe.db.exists("CRM Lead", self.lead):
			frappe.throw(_("Lead {0} no longer exists.").format(self.lead))
		if self.contact and not frappe.db.exists("Contact", self.contact):
			frappe.throw(_("Contact {0} no longer exists.").format(self.contact))
		return erasure.resolve_subject(lead=self.lead, contact=self.contact)


def check_can_decide(request, user: str, roles: list[str]) -> None:
	"""Only the Privacy team decides, and never on a request they logged themselves."""
	if request.status != "Pending Approval":
		frappe.throw(_("This request is already {0}.").format(_(request.status).lower()))
	if PRIVACY_ROLE not in roles:
		frappe.throw(_("Only the Privacy team can approve or reject erasure requests."), frappe.PermissionError)
	if user in (request.requested_by, request.owner):
		frappe.throw(
			_("You logged this request, so someone else on the Privacy team has to decide on it."),
			frappe.PermissionError,
		)


def add_business_days(start, days: int) -> datetime.date:
	"""The date `days` working days (Monday to Friday) after `start`."""
	current = getdate(start)
	while days > 0:
		current += datetime.timedelta(days=1)
		if current.weekday() < 5:
			days -= 1
	return current


def was_erased(lead: str) -> bool:
	return bool(frappe.db.exists("CRM Data Erasure Request", {"lead": lead, "status": "Completed"}))


@frappe.whitelist()
def get_requests(lead: str | None = None, contact: str | None = None) -> list[dict]:
	"""Erasure requests for a lead or contact, for the banner and dialog on its page."""
	if not lead and not contact:
		return []
	if lead:
		frappe.has_permission("CRM Lead", doc=lead, throw=True)
	if contact:
		frappe.has_permission("Contact", doc=contact, throw=True)

	filters = {"lead": lead} if lead else {"contact": contact}
	# Reps see whether a request exists even when someone else logged it, so they
	# don't log a duplicate, but only these status fields.
	return frappe.get_all(
		"CRM Data Erasure Request",
		filters=filters,
		fields=["name", "status", "received_on", "respond_by", "requested_by", "decided_on"],
		order_by="creation desc",
	)
