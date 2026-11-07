# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""What the approval preview calls each kind of the erasure plan, and how a record behind a link is titled."""

import frappe

# kind -> (doctype, label). Labels are what the screen says; the doctype names the records behind the links.
KIND_INFO = {
	"leads": ("CRM Lead", "Leads"),
	"deals_on": ("CRM Deal", "Deals she is on"),
	"deals_copy": ("CRM Deal", "Won or lost deals that list her contact (her contact details only)"),
	"deals_removed": ("CRM Deal", "Open deals she was removed from (emails and calls with her details only)"),
	"contacts": ("Contact", "Contacts"),
	"addresses": ("Address", "Addresses"),
	"communications": ("Communication", "Emails"),
	"call_logs": ("CRM Call Log", "Call logs"),
	"notes": ("FCRM Note", "Notes"),
	"tasks": ("CRM Task", "Tasks"),
	"comments": ("Comment", "Comments"),
	"todos": ("ToDo", "To-dos"),
	"files": ("File", "Files"),
	"versions": ("Version", "Change history entries"),
	"deleted_documents": ("Deleted Document", "Deleted copies of records"),
	"crm_notifications": ("CRM Notification", "Notifications"),
	"notification_logs": ("Notification Log", "Notification logs"),
	"email_queues": ("Email Queue", "Queued emails"),
	"wa_messages": ("WA Message", "WhatsApp messages"),
	"wa_profiles": ("WA Profile", "WhatsApp profiles"),
	"event_participants": ("Event Participants", "Event participants"),
	"failed_sync_logs": ("Failed Lead Sync Log", "Failed lead sync logs"),
	"enrichment_changes": ("CRM Enrichment Run Change", "Enrichment changes"),
	"activity_logs": ("Activity Log", "Activity logs"),
	"unhandled_emails": ("Unhandled Email", "Unhandled emails"),
	"events": ("Event", "Events she is invited to (text that names her only)"),
	"route_history": ("Route History", "Route history entries"),
	"user_settings": ("__UserSettings", "Saved list filters"),
	"hold_notifications": ("CRM Notification", "Notices about this request (deleted)"),
	"hold_notification_logs": ("Notification Log", "Notice logs about this request (deleted)"),
	"hold_emails": ("Email Queue", "Emails about this request (deleted)"),
}
TITLE_FIELDS = {
	"CRM Lead": "lead_name",
	"Contact": "full_name",
	"CRM Deal": "organization",
	"Address": "address_title",
	"Communication": "subject",
	"FCRM Note": "title",
	"CRM Task": "title",
}


def label_of(doctype: str, name: str) -> str:
	field = TITLE_FIELDS.get(doctype)
	return (field and frappe.db.get_value(doctype, name, field)) or name
