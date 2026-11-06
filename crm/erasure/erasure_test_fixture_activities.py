# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt
"""Marisol fixture, activity: emails, calls, notes, tasks, comments, notifications, each beside a near miss

Inserted raw (no hooks), so the expected rows are exactly the ones listed here plus the rows the
real person inserts created through hooks (`record_side_effects`).
"""

import frappe

from crm.erasure.erasure_test_fixture_base import (
	COLLEAGUE_EMAIL,
	EXPECTED,
	HER_EMAILS,
	HER_PHONE_DATA,
	HIDDEN,
	NEAR_EMAIL,
	NEAR_MISSES,
	NEAR_PHONE,
	REP_PHONE,
	MarisolFixture,
)
from crm.fcrm.doctype.crm_erasure_request.erasure_test_fixtures import REP

# Rows that inserting her lead and deals creates through hooks (assignments, notifications, mail)
SIDE_EFFECTS = {
	"ToDo": ("reference_type", "reference_name", EXPECTED),
	"Comment": ("reference_doctype", "reference_name", EXPECTED),
	"CRM Notification": ("reference_doctype", "reference_name", EXPECTED),
	"Notification Log": ("document_type", "document_name", EXPECTED),
	"Email Queue": ("reference_doctype", "reference_name", HIDDEN),
	"Version": ("ref_doctype", "docname", HIDDEN),
}
EMAIL_DEFAULTS = {
	"communication_type": "Communication",
	"communication_medium": "Email",
	"status": "Linked",
	"sent_or_received": "Sent",
	"subject": "Quote",
	"content": "Hi Marisol",
	"sender": REP,
}
MENTION = {"type": "Mention", "to_user": REP}


def add_activities(fx: MarisolFixture):
	record_side_effects(fx)
	_add_communications(fx)
	_add_calls_notes_and_tasks(fx)
	_add_comments_and_notifications(fx)


def record_side_effects(fx: MarisolFixture):
	"""Hook-created rows on her records exist in production too: discovery must find them"""
	refs = [
		("CRM Lead", fx.lead),
		("CRM Deal", fx.deal_won),
		("CRM Deal", fx.deal_open),
		("Contact", fx.contact),
	]
	for doctype, (dt_col, name_col, bucket) in SIDE_EFFECTS.items():
		for ref_doctype, ref_name in refs:
			names = frappe.get_all(doctype, filters={dt_col: ref_doctype, name_col: ref_name}, pluck="name")
			getattr(fx, bucket)[doctype].update(str(name) for name in names)


def _add_communications(fx: MarisolFixture):
	her = f"Marisol Reyes <{HER_EMAILS[0]}>"
	on_colleague_deal = {"reference_doctype": "CRM Deal", "reference_name": fx.colleague_deal}

	def email(bucket, label, **values):
		fx.seed(bucket, label, "Communication", **{**EMAIL_DEFAULTS, **values})

	email(EXPECTED, "comm_on_lead", reference_doctype="CRM Lead", reference_name=fx.lead, recipients=her)
	cc = f"Kai <{COLLEAGUE_EMAIL}>, M Reyes <m.reyes@EXAMPLE.net>"  # her second address, other case
	email(EXPECTED, "comm_cc_on_colleague_deal", recipients=COLLEAGUE_EMAIL, cc=cc, **on_colleague_deal)
	email(EXPECTED, "comm_from_her", sender=her, sent_or_received="Received", recipients=REP)
	email(EXPECTED, "comm_sms", communication_medium="SMS", phone_no="+14155550177", recipients=None)
	timeline = [{"link_doctype": "Contact", "link_name": fx.contact}]
	email(EXPECTED, "comm_timeline", recipients=REP, timeline_links=timeline)
	email(NEAR_MISSES, "near_comm_email", sender=NEAR_EMAIL, recipients=REP)
	email(NEAR_MISSES, "near_comm_phone", communication_medium="SMS", phone_no=NEAR_PHONE)
	email(NEAR_MISSES, "near_comm_colleague", recipients=COLLEAGUE_EMAIL, **on_colleague_deal)


def _add_calls_notes_and_tasks(fx: MarisolFixture):
	note_by_call = fx.seed(EXPECTED, "note_by_call", "FCRM Note", title="Call notes")
	on_deal = {"reference_doctype": "CRM Deal", "reference_docname": fx.deal_won}
	fx.seed(EXPECTED, "note_on_deal", "FCRM Note", title="Budget", **on_deal)
	on_lead = {"reference_doctype": "CRM Lead", "reference_docname": fx.lead}
	task = fx.seed(EXPECTED, "task_on_lead", "CRM Task", title="Send quote", **on_lead)
	task_by_call = fx.seed(EXPECTED, "task_by_call", "CRM Task", title="Call back")
	on_task = {"reference_type": "CRM Task", "reference_name": task, "allocated_to": REP}
	fx.seed(EXPECTED, "todo_on_task", "ToDo", description="Send quote", **on_task)

	def call(bucket, label, **values):
		defaults = {"type": "Outgoing", "status": "Completed", "from": REP_PHONE, "to": REP_PHONE}
		fx.seed(bucket, label, "CRM Call Log", id=frappe.generate_hash(length=12), **{**defaults, **values})

	call(
		EXPECTED,
		"call_on_lead",
		**on_lead,
		to=HER_PHONE_DATA[0],
		note=note_by_call,
		recording_url="https://calls.example.net/rec/1",
		links=[{"link_doctype": "CRM Task", "link_name": task_by_call}],
	)
	call(EXPECTED, "call_from_her", type="Incoming", **{"from": "+1 415 555 0177"})
	call(NEAR_MISSES, "near_call", to=NEAR_PHONE)


def _add_comments_and_notifications(fx: MarisolFixture):
	def comment(bucket, label, reference_doctype, reference_name, **values):
		values = {"comment_type": "Comment", "content": "Noted", "comment_email": REP, **values}
		reference = {"reference_doctype": reference_doctype, "reference_name": reference_name}
		return fx.seed(bucket, label, "Comment", **reference, **values)

	on_lead = comment(EXPECTED, "comment_on_lead", "CRM Lead", fx.lead, content="Prefers email")
	comment(EXPECTED, "comment_on_comm", "Communication", fx.names["comm_from_her"])
	# reachable two ways: through her email thread and through its own comment_email
	comm, by_her = fx.names["comm_from_her"], {"comment_email": HER_EMAILS[1]}
	comment(EXPECTED, "comment_on_comm_by_her", "Communication", comm, **by_her)
	comment(EXPECTED, "comment_by_her", "CRM Deal", fx.colleague_deal, comment_email=HER_EMAILS[0])
	comment(NEAR_MISSES, "comment_on_colleague_deal", "CRM Deal", fx.colleague_deal)

	lead_ref = {"reference_doctype": "CRM Lead", "reference_name": fx.lead, "message": "Marisol"}
	fx.seed(EXPECTED, "notification_on_lead", "CRM Notification", **MENTION, **lead_ref)
	on_comment = {"notification_type_doctype": "Comment", "notification_type_doc": on_lead}
	fx.seed(EXPECTED, "notification_on_comment", "CRM Notification", **MENTION, **on_comment)
	on_deal = {"document_type": "CRM Deal", "document_name": fx.deal_won, "for_user": REP}
	fx.seed(EXPECTED, "notification_log_on_deal", "Notification Log", subject="Won", **on_deal)
