# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt
"""Registry entries for activity around her records and the files attached to them

Rows are kept (dashboards count them) with their content replaced by the marker.
"""

from crm.erasure.registry_model import (
	ACTIVITY,
	ANY_MATCH,
	CLEAR,
	CLEAR_IF_HERS,
	DELETE_PERMANENTLY,
	DELETE_ROWS,
	DROP_HER_LINKS,
	FILE,
	MARKER,
	MARKER_IF_HERS,
	NAME_MARKER,
	PERSON,
	REMOVE_ADDRESS,
	REPLACE_CONTENT,
	SCRUB,
	SUBJECTS,
	Backref,
	ChildBackref,
	ChildLink,
	Emails,
	Entry,
	Link,
	Phones,
	Ref,
)

WHATSAPP = "whatsapp"

ACTIVITY_ENTRIES = (
	Entry(
		doctype="Communication",
		kind=ACTIVITY,
		found_by="Emails and SMS referencing or timeline-linked to her records; her address in sender, recipients, cc or bcc; phone_no is hers",
		action=REPLACE_CONTENT,
		finders=(
			Ref("reference_doctype", "reference_name"),
			ChildLink("Communication Link"),
			Emails(("sender", "recipients", "cc", "bcc")),
			Phones(("phone_no",)),
		),
		fields=(
			("subject", MARKER),
			("content", MARKER),
			("text_content", MARKER),
			("sender", REMOVE_ADDRESS),
			("sender_full_name", CLEAR_IF_HERS, "sender"),
			("recipients", REMOVE_ADDRESS),
			("cc", REMOVE_ADDRESS),
			("bcc", REMOVE_ADDRESS),
			("phone_no", CLEAR_IF_HERS, "phone_no"),
		),
		keep=(
			"communication_type",
			"communication_medium",
			"sent_or_received",
			"communication_date",
			"status",
		),
	),
	Entry(
		doctype="CRM Call Log",
		kind=ACTIVITY,
		found_by="Calls referencing or linked to her records; from or to is her number",
		action=SCRUB,
		finders=(
			Ref("reference_doctype", "reference_docname"),
			ChildLink("Dynamic Link"),
			Phones(("from", "to")),
		),
		fields=(("from", MARKER_IF_HERS, "from"), ("to", MARKER_IF_HERS, "to"), ("recording_url", CLEAR)),
		keep=("duration", "status", "type", "start_time", "end_time", "caller", "receiver"),
	),
	Entry(
		doctype="FCRM Note",
		kind=ACTIVITY,
		found_by="Notes referencing her records; the note of one of her calls",
		action=REPLACE_CONTENT,
		finders=(
			Ref("reference_doctype", "reference_docname"),
			Backref("CRM Call Log", "note"),
			ChildBackref("CRM Call Log"),
		),
		fields=(("title", MARKER), ("content", MARKER)),
		keep=("pinned", "pinned_by", "reference_doctype", "reference_docname"),
	),
	Entry(
		doctype="CRM Task",
		kind=ACTIVITY,
		found_by="Tasks referencing her records or linked to one of her calls",
		action=REPLACE_CONTENT,
		finders=(Ref("reference_doctype", "reference_docname"), ChildBackref("CRM Call Log")),
		fields=(("title", MARKER), ("description", MARKER)),
		keep=("status", "priority", "due_date", "assigned_to"),
	),
	Entry(
		doctype="WA Profile",
		kind=PERSON,
		app=WHATSAPP,
		found_by="WhatsApp profiles whose phone_number or wa_id is her number, or linked to her records",
		action=SCRUB,
		finders=(Phones(("phone_number", "wa_id")), ChildLink("Dynamic Link")),
		fields=(
			("phone_number", NAME_MARKER),
			("wa_id", CLEAR),
			("profile_name", NAME_MARKER),
			("links", DROP_HER_LINKS),
		),
		keep=("whatsapp_account", "status", "message_count", "last_message_at"),
	),
	Entry(
		doctype="WA Message",
		kind=ACTIVITY,
		app=WHATSAPP,
		found_by="WhatsApp messages to one of her profiles or referencing her records; from is her number",
		action=REPLACE_CONTENT,
		finders=(Link("to", "WA Profile"), Ref("reference_doctype", "reference_docname"), Phones(("from",))),
		fields=(
			("message", MARKER),
			("reaction", CLEAR),
			("template_body_parameters", CLEAR),
			("template_header_parameters", CLEAR),
			("interactive_buttons", DELETE_ROWS),
			("interactive_list_items", DELETE_ROWS),
			("media_url", CLEAR),
			("media_id", CLEAR),
			("attach", CLEAR),
			("from", CLEAR_IF_HERS, "from"),
		),
		keep=("direction", "status", "timestamp", "whatsapp_account", "to", "message_id"),
	),
	Entry(
		doctype="Comment",
		kind=ACTIVITY,
		found_by="Comments on her records or on any of her activity; comment_email is hers",
		action=REPLACE_CONTENT,
		finders=(Ref("reference_doctype", "reference_name", ANY_MATCH), Emails(("comment_email",))),
		fields=(
			("content", MARKER),
			("subject", MARKER),
			("comment_email", CLEAR_IF_HERS, "comment_email"),
			("comment_by", CLEAR_IF_HERS, "comment_email"),
			("ip_address", CLEAR_IF_HERS, "comment_email"),
		),
		keep=("comment_type", "reference_doctype", "reference_name"),
	),
	Entry(
		doctype="ToDo",
		kind=ACTIVITY,
		found_by="ToDos (assignments) on her records or on her CRM Tasks",
		action=REPLACE_CONTENT,
		finders=(Ref("reference_type", "reference_name", (*SUBJECTS, "CRM Task")),),
		fields=(("description", MARKER),),
		keep=("status", "allocated_to", "date", "reference_type", "reference_name"),
	),
	Entry(
		doctype="CRM Notification",
		kind=ACTIVITY,
		found_by="CRM notifications whose reference, notification document or comment is a match",
		action=REPLACE_CONTENT,
		finders=(
			Ref("reference_doctype", "reference_name", ANY_MATCH),
			Ref("notification_type_doctype", "notification_type_doc", ANY_MATCH),
			Link("comment", "Comment"),
		),
		fields=(("message", MARKER), ("notification_text", MARKER)),
		keep=("type", "to_user", "from_user", "read"),
	),
	Entry(
		doctype="Notification Log",
		kind=ACTIVITY,
		found_by="Desk notifications whose document is a match",
		action=REPLACE_CONTENT,
		finders=(Ref("document_type", "document_name", ANY_MATCH),),
		fields=(("title", MARKER), ("subject", MARKER), ("description", MARKER), ("email_content", MARKER)),
		keep=("type", "for_user", "read", "document_type", "document_name"),
	),
	Entry(
		doctype="File",
		kind=FILE,
		found_by=(
			"File rows attached to any match (her lead or contact image is the File row attached to that "
			"record). The row is deleted; the file on disk only after commit and only when no File row "
			"outside her matches shares its file_url (uploads are deduplicated by content)"
		),
		action=DELETE_PERMANENTLY,
		# never by file_url: a deduplicated upload's other File rows belong to other records
		finders=(Ref("attached_to_doctype", "attached_to_name", ANY_MATCH),),
	),
)
