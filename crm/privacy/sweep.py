"""The erasure step that wipes her activities and the side tables that copy her details.

Runs inside `run_erasure`, after `erase_records` has renamed her contacts and addresses
(`plan.contacts` and `plan.addresses` hold the new names). Like that step it writes only
through `frappe.db.set_value(..., update_modified=False)`, `frappe.db.delete`,
`frappe.qb.update` and a plain insert of new Comment and checklist rows. Anything that
cannot be undone by a rollback (removing files from disk, re-indexing search) is appended
to `after_commit`, which `run_erasure` registers only when the whole erasure succeeds.

Placeholders: P = `erased_person(request)` for addresses, names and numbers, C =
`erased_content(request)` for subjects, bodies, notes, tasks and comments. R is her
confirmed leads, contacts and the deals she is still on.
"""

import os
import re
from collections.abc import Callable
from contextlib import suppress
from email.utils import getaddresses
from functools import partial

import frappe
from frappe.model.document import Document
from frappe.query_builder import Criterion
from frappe.utils import get_url

from crm.privacy.identifiers import PHONE_REGION, normalize_email, normalize_identifier, personal_fields
from crm.privacy.matching import _digits, like_escape, phone_rows
from crm.privacy.plan import RECORDINGS_ITEM, ErasurePlan
from crm.privacy.rules import erased_content, erased_file, erased_person, replace_addresses, scrub_identifiers
from crm.utils import phone_search_digits

DOCTYPE = "CRM Erasure Request"
CHECKLIST_ITEM = "CRM Erasure Checklist Item"
LEAD, DEAL, CONTACT = "CRM Lead", "CRM Deal", "Contact"
ADDRESS_HEADERS = ("sender", "recipients", "cc", "bcc")
PENDING_EMAIL = ("Not Sent", "Partially Sent")  # EmailQueue.is_to_be_sent
# Activities whose rows feed Frappe's global search (fields marked in_global_search).
GLOBAL_SEARCH_DOCTYPES = ("Communication", "FCRM Note", "CRM Task", "CRM Call Log")
_SEPARATORS = re.compile(r"[\s\-().+]")

Targets = dict[str, list[str]]


# --- shared helpers ---------------------------------------------------------------------


def _exists(doctype: str) -> bool:
	"""The doctype is installed (whatsapp and enrichment may not be)."""
	return bool(frappe.db.exists("DocType", doctype)) and frappe.db.table_exists(doctype)


def _fields(doctype: str, fieldnames) -> list[str]:
	meta = frappe.get_meta(doctype)
	return [fieldname for fieldname in fieldnames if meta.has_field(fieldname)]


def _set(doctype: str, name: str, values: dict) -> None:
	if values:
		frappe.db.set_value(doctype, name, values, update_modified=False)


def _wipe(doctype: str, names, fieldnames, placeholder: str) -> None:
	"""Put `placeholder` in each set field of `fieldnames` on the named rows."""
	fields = _fields(doctype, fieldnames)
	if not fields:
		return
	for name in names:
		row = frappe.db.get_value(doctype, name, fields, as_dict=True) or {}
		_set(doctype, name, {field: placeholder for field in fields if row.get(field)})


def _referencing(doctype: str, doctype_field: str, name_field: str, targets: Targets) -> set[str]:
	"""Names of `doctype` rows whose (doctype_field, name_field) point at any of `targets`."""
	if not _fields(doctype, (doctype_field, name_field)):
		return set()
	table = frappe.qb.DocType(doctype)
	found: set[str] = set()
	for target, names in targets.items():
		if names:
			rows = (
				frappe.qb.from_(table)
				.select(table.name)
				.where((getattr(table, doctype_field) == target) & getattr(table, name_field).isin(names))
				.run()
			)
			found.update(row[0] for row in rows)
	return found


def _mentioning(doctype: str, fieldnames, emails: set[str], phones: set[str]) -> set[str]:
	"""Names of `doctype` rows whose text might hold one of her emails or phones.

	A coarse SQL prefilter (email substring, or the phone's digits once separators are
	dropped); callers confirm with `scrub_identifiers` or exact comparison.
	"""
	fields = _fields(doctype, fieldnames)
	table = frappe.qb.DocType(doctype)
	conditions = []
	for field in fields:
		column = getattr(table, field)
		conditions += [column.like(f"%{like_escape(email)}%") for email in sorted(emails) if email]
		for phone in sorted(phones):
			digits = phone_search_digits(phone, PHONE_REGION)
			if digits:
				conditions.append(_digits(column).like(f"%{like_escape(digits)}%"))
	if not conditions:
		return set()
	return {row[0] for row in frappe.qb.from_(table).select(table.name).where(Criterion.any(conditions)).run()}


def _sweep_text(
	doctype: str,
	fieldnames,
	referenced: set[str],
	mentioning: set[str],
	plan: ErasurePlan,
	content: str,
	person: str,
) -> None:
	"""Rows in `referenced` get `content` in every set text field; the other rows in
	`mentioning` get her emails and phones replaced by `person`."""
	fields = _fields(doctype, fieldnames)
	if not fields:
		return
	for name in sorted(referenced | mentioning):
		row = frappe.db.get_value(doctype, name, fields, as_dict=True) or {}
		values = {}
		for field in fields:
			value = row.get(field)
			if not value or not isinstance(value, str):
				continue
			new = content if name in referenced else scrub_identifiers(value, plan.emails, plan.phones, person)
			if new != value:
				values[field] = new
		_set(doctype, name, values)


def _her_address(header: str | None, emails: set[str]) -> bool:
	return any(normalize_email(addr) in emails for _name, addr in getaddresses([header or ""]) if addr)


def _run_guarded(request: str, fn: Callable) -> None:
	try:
		fn()
	except Exception:
		# A fixed message keeps the traceback (paths, her values in locals) out of the Error
		# Log; nothing escapes, so frappe still runs the callbacks queued after this one.
		with suppress(Exception):
			frappe.log_error(
				title=f"Erasure {request}: a clean-up step after the erasure failed",
				message="A clean-up step after the erasure failed.",
				reference_doctype=DOCTYPE,
				reference_name=request,
			)


def guarded(request: str, fn: Callable) -> Callable:
	"""`fn` wrapped for `frappe.db.after_commit`: a failure is logged and the next callback still runs."""
	return partial(_run_guarded, request, fn)


def _reindex(doctype: str, name: str) -> None:
	from crm.search_sqlite import CRMSearch

	search = CRMSearch()
	if search.is_search_enabled() and search.index_exists():
		search.index_doc(doctype, name)


def _queue_reindex(after_commit: list[Callable], doctype: str, names) -> None:
	for name in dict.fromkeys(names):
		after_commit.append(partial(_reindex, doctype, name))


def flush_search_queue() -> None:
	"""Write out the queued global search entries now.

	An entry queued (in Redis) before the erasure still holds her values; synced after a
	row is dropped here it would re-create it, so the queue is flushed before deleting.
	"""
	from frappe.utils.global_search import sync_global_search

	# A failure (Redis down) must not stop the caller from dropping the rows.
	with suppress(Exception):
		sync_global_search()


def _drop_global_search(doctype: str, names: list[str]) -> None:
	"""After the commit: remove the rows' global search entries (subject, sender…).

	set_value does not refresh `__global_search`, and it is MyISAM, outside the
	transaction, so this runs only once the erasure has committed.
	"""
	flush_search_queue()
	for start in range(0, len(names), 500):
		frappe.db.delete("__global_search", {"doctype": doctype, "name": ["in", names[start : start + 500]]})


def _queue_global_search_removal(after_commit: list[Callable], activities: dict[str, list[str]]) -> None:
	for doctype in GLOBAL_SEARCH_DOCTYPES:
		names = list(dict.fromkeys(activities.get(doctype) or []))
		if names and frappe.get_meta(doctype).get_global_search_fields():
			after_commit.append(partial(_drop_global_search, doctype, names))


# --- communications -----------------------------------------------------------------------


def erase_communications(names: list[str], emails: set[str], phones: set[str], request: str) -> None:
	"""Wipe the named Communications. They are never deleted.

	Subject and body become C. Her addresses in sender/recipients/cc/bcc become P, the
	others stay. The sender's name becomes P when she sent it, the phone number when it
	is hers. Link titles that quote her email or phone are scrubbed (titles of links to
	her records were already replaced by `erase_records`).
	"""
	person, content = erased_person(request), erased_content(request)
	fields = _fields("Communication", ("subject", "content", "text_content", "sender_full_name", "phone_no"))
	fields += _fields("Communication", ADDRESS_HEADERS)
	for name in dict.fromkeys(names):
		row = frappe.db.get_value("Communication", name, fields, as_dict=True)
		if not row:
			continue
		values = {"subject": content, "content": content}
		if row.get("text_content"):
			values["text_content"] = content
		for header in ADDRESS_HEADERS:
			if row.get(header):
				new = replace_addresses(row[header], emails, person)
				if new != row[header]:
					values[header] = new
		if row.get("sender_full_name") and _her_address(row.get("sender"), emails):
			values["sender_full_name"] = person
		if row.get("phone_no") and normalize_identifier("Phone", row.phone_no) in phones:
			values["phone_no"] = person
		_set("Communication", name, {field: value for field, value in values.items() if field in fields})

		for link in frappe.get_all(
			"Communication Link",
			filters={"parenttype": "Communication", "parent": name},
			fields=["name", "link_title"],
			parent_doctype="Communication",
		):
			title = scrub_identifiers(link.link_title, emails, phones, person) if link.link_title else ""
			if link.link_title and title != link.link_title:
				frappe.db.set_value("Communication Link", link.name, "link_title", title, update_modified=False)


# --- call logs, notes, tasks, comments ----------------------------------------------------


def _sweep_call_logs(plan: ErasurePlan, doc: Document, person: str) -> list[str]:
	"""Her numbers and recordings on the call logs. Returns the notes they link to."""
	notes: list[str] = []
	if not plan.call_logs:
		return notes
	table = frappe.qb.DocType("CRM Call Log")
	rows = (
		frappe.qb.from_(table)
		.select(table.name, table["from"], table.to, table.recording_url, table.note)
		.where(table.name.isin(plan.call_logs))
		.run(as_dict=True)
	)
	for row in rows:
		numbers = [
			field
			for field in ("from", "to")
			if row.get(field) and normalize_identifier("Phone", row.get(field)) in plan.phones
		]
		query = frappe.qb.update(table)
		for field in numbers:
			query = query.set(table[field], person)
		if row.recording_url:
			query = query.set(table.recording_url, None)
		if numbers or row.recording_url:
			query.where(table.name == row.name).run()
		if row.note:
			notes.append(row.note)
	if plan.has_recordings:
		_add_checklist_item(doc.name, RECORDINGS_ITEM)
	return notes


def _add_checklist_item(request: str, description: str) -> None:
	"""Add a checklist row to the request once. A system write: inserted directly."""
	existing = frappe.get_all(
		CHECKLIST_ITEM,
		filters={"parent": request, "parenttype": DOCTYPE, "parentfield": "checklist"},
		fields=["description", "idx"],
		parent_doctype=DOCTYPE,
	)
	if any(row.description == description for row in existing):
		return
	_insert(
		{
			"doctype": CHECKLIST_ITEM,
			"parent": request,
			"parenttype": DOCTYPE,
			"parentfield": "checklist",
			"idx": max((row.idx or 0 for row in existing), default=0) + 1,
			"description": description,
		}
	)


def _insert(values: dict) -> None:
	"""Insert a new row without controller hooks (no realtime, mentions or queued jobs)."""
	doc = frappe.get_doc(values)
	doc.set_user_and_timestamp()
	doc.db_insert()


def _reset_comment_caches(records: Targets) -> None:
	for doctype, names in records.items():
		for name in names:
			frappe.db.set_value(doctype, name, "_comments", "[]", update_modified=False)


# --- files ----------------------------------------------------------------------------------


def _disk_path(file_url: str | None) -> str | None:
	"""Where a locally stored file lives, or None for remote URLs and anything unexpected."""
	url = file_url or ""
	site_url = get_url()
	if url.startswith(site_url) and "/files/" in url:
		url = url[len(site_url) :]
	for prefix, folder in (("/private/files/", "private"), ("/files/", "public")):
		if url.startswith(prefix):
			parts = url[len(prefix) :].split("/")
			if not all(part and part not in (".", "..") for part in parts):
				return None
			return frappe.get_site_path(folder, "files", *parts)
	return None


def _in_use(file_url: str) -> bool:
	return bool(
		frappe.db.exists("File", {"file_url": file_url}) or frappe.db.exists("File", {"thumbnail_url": file_url})
	)


def _remove_from_disk(request: str, file_url: str, path: str) -> None:
	"""After the commit: delete the stored file unless a File row has started using it."""
	if _in_use(file_url):
		return
	try:
		os.remove(path)
	except FileNotFoundError:
		pass
	except OSError:
		# Without a message log_error would store the traceback, whose OSError text holds the
		# path (often her name). The fixed message keeps it out. Other callbacks still run.
		frappe.log_error(
			title=f"Erasure {request}: a file could not be removed from disk",
			message="A file could not be removed from disk.",
			reference_doctype=DOCTYPE,
			reference_name=request,
		)


def delete_files(filters: dict, request: str, after_commit: list[Callable]) -> list:
	"""Delete the File rows matching `filters` (never folders) and queue, on `after_commit`,
	the removal from disk of each stored file no remaining File row uses. Returns the rows.

	Blob-backed rows (File Storage v2) leave their bytes to the storage garbage collector.
	"""
	rows = frappe.get_all(
		"File",
		filters={**filters, "is_folder": 0},
		fields=[
			"name",
			*_fields("File", ("file_url", "thumbnail_url", "attached_to_doctype", "attached_to_name", "blob")),
		],
	)
	if not rows:
		return []
	frappe.db.delete("File", {"name": ["in", [row.name for row in rows]]})

	urls: dict[str, None] = {}
	for row in rows:
		if row.get("blob"):
			continue
		for url in (row.get("file_url"), row.get("thumbnail_url")):
			if url:
				urls[url] = None
	for url in urls:
		path = _disk_path(url)
		# Bytes another File row still lists are shared with another record and stay.
		if path and not _in_use(url):
			after_commit.append(partial(_remove_from_disk, request, url, path))
	return rows


def _sweep_files(plan: ErasurePlan, records: Targets, request: str, after_commit: list[Callable]) -> None:
	"""Delete her File rows; note each one removed from her records; free unshared disk files."""
	if not plan.files:
		return
	rows = delete_files({"name": ["in", plan.files]}, request, after_commit)

	placeholder = erased_file(request)
	for row in rows:
		if row.attached_to_name in records.get(row.attached_to_doctype, ()):
			_insert(
				{
					"doctype": "Comment",
					"comment_type": "Info",
					"comment_email": frappe.session.user,
					"reference_doctype": row.attached_to_doctype,
					"reference_name": row.attached_to_name,
					"content": placeholder,
				}
			)


# --- side tables ----------------------------------------------------------------------------


def _sweep_notifications(plan: ErasurePlan, targets: Targets, content: str, person: str) -> None:
	doctype, fields = "CRM Notification", ("message", "notification_text")
	referenced = _referencing(doctype, "reference_doctype", "reference_name", targets)
	referenced |= _referencing(doctype, "notification_type_doctype", "notification_type_doc", targets)
	mentioning = _mentioning(doctype, fields, plan.emails, plan.phones)
	_sweep_text(doctype, fields, referenced, mentioning, plan, content, person)


def _sweep_notification_logs(plan: ErasurePlan, targets: Targets, content: str, person: str) -> None:
	doctype, fields = "Notification Log", ("subject", "email_content", "title", "description")
	referenced = _referencing(doctype, "document_type", "document_name", targets)
	referenced |= _referencing(doctype, "source_doctype", "source_name", targets)
	mentioning = _mentioning(doctype, fields, plan.emails, plan.phones)
	_sweep_text(doctype, fields, referenced, mentioning, plan, content, person)


def _sweep_todos(plan: ErasurePlan, targets: Targets, content: str, person: str) -> None:
	doctype, fields = "ToDo", ("description",)
	referenced = _referencing(doctype, "reference_type", "reference_name", targets)
	mentioning = _mentioning(doctype, fields, plan.emails, plan.phones)
	_sweep_text(doctype, fields, referenced, mentioning, plan, content, person)


def _sweep_email_queue(plan: ErasurePlan, targets: Targets, content: str, person: str) -> None:
	"""Queued emails about her, to her, or quoting her email: the message becomes C.

	Her addresses among the recipients become P. The stored message may be encoded, so a
	queue row is judged by its references and recipients as well as its text.
	"""
	recipients: dict[str, str] = {}
	for name in _mentioning("Email Queue Recipient", ("recipient",), plan.emails, set()):
		row = frappe.db.get_value("Email Queue Recipient", name, ["parent", "recipient"], as_dict=True)
		if row and normalize_email(row.recipient) in plan.emails:
			recipients[name] = row.parent
	for name in recipients:
		frappe.db.set_value("Email Queue Recipient", name, "recipient", person, update_modified=False)

	queued = _referencing("Email Queue", "reference_doctype", "reference_name", targets)
	if plan.communications:
		queued |= set(frappe.get_all("Email Queue", {"communication": ["in", plan.communications]}, pluck="name"))
	queued |= set(recipients.values())
	for name in _mentioning("Email Queue", ("message",), plan.emails, plan.phones) - queued:
		if _holds_identifier(frappe.db.get_value("Email Queue", name, "message"), plan):
			queued.add(name)
	# Still waiting to go out: a wiped message would be sent as a bare placeholder, so the
	# whole queued email goes. Rows already sent are kept as a record, with the message wiped.
	pending = (
		set(frappe.get_all("Email Queue", {"name": ["in", list(queued)], "status": ["in", PENDING_EMAIL]}, pluck="name"))
		if queued
		else set()
	)
	if pending:
		frappe.db.delete("Email Queue Recipient", {"parenttype": "Email Queue", "parent": ["in", list(pending)]})
		frappe.db.delete("Email Queue", {"name": ["in", list(pending)]})
	_wipe("Email Queue", queued - pending, ("message",), content)

	cc = _mentioning("Email Queue", ("show_as_cc",), plan.emails, set())
	for name in cc:
		value = frappe.db.get_value("Email Queue", name, "show_as_cc")
		new = replace_addresses(value, plan.emails, person)
		if new != value:
			frappe.db.set_value("Email Queue", name, "show_as_cc", new, update_modified=False)
	errors = _mentioning("Email Queue", ("error",), plan.emails, plan.phones)
	_sweep_text("Email Queue", ("error",), set(), errors, plan, content, person)


def _delete_whatsapp_media(messages: list[str], request: str, after_commit: list[Callable]) -> None:
	"""Delete the media files of the messages, before `attach` is blanked.

	Received media is a File attached to the WA Message. Sent media is the upload that
	`attach` names (a File name, or a URL in older whatsapp versions), attached to no record;
	one attached to a record stays with that record.
	"""
	delete_files({"attached_to_doctype": "WA Message", "attached_to_name": ["in", messages]}, request, after_commit)
	if not _fields("WA Message", ("attach",)):
		return
	attached = [a for a in frappe.get_all("WA Message", {"name": ["in", messages]}, pluck="attach") if a]
	if attached:
		for key in ("name", "file_url"):
			delete_files({key: ["in", attached], "attached_to_doctype": ["is", "not set"]}, request, after_commit)


def _sweep_whatsapp(
	plan: ErasurePlan, records: Targets, content: str, person: str, request: str, after_commit: list[Callable]
) -> None:
	if not (_exists("WA Message") and _exists("WA Profile")):
		return
	profiles: list[str] = []
	for phone in sorted(plan.phones):
		profiles += [row.name for row in phone_rows("WA Profile", ["phone_number"], phone)]
	profiles = list(dict.fromkeys(profiles))

	messages = _referencing("WA Message", "reference_doctype", "reference_docname", records)
	if profiles:
		messages |= set(frappe.get_all("WA Message", {"to": ["in", profiles]}, pluck="name"))
	if messages:
		_delete_whatsapp_media(sorted(messages), request, after_commit)
	_wipe("WA Message", messages, ("message",), content)
	# media_url holds the incoming document's file name; attach names the media File
	_wipe(
		"WA Message", messages, ("template_body_parameters", "template_header_parameters", "media_url", "attach"), ""
	)
	_sweep_text("WA Message", ("error_message",), set(), messages, plan, content, person)

	_wipe("WA Profile", profiles, ("phone_number", "profile_name", "wa_id"), person)
	_sweep_wa_logs(plan, content)


def _sweep_wa_logs(plan: ErasurePlan, content: str) -> None:
	"""Webhook and API logs holding her number or email: the payloads go, the message becomes C.

	Each webhook call logs its full payload (her wa_id, profile name and message text).
	"""
	doctype = "WA Log"
	if not _exists(doctype):
		return
	fields = _fields(doctype, ("request_data", "response_data", "message"))
	for name in _mentioning(doctype, fields, plan.emails, plan.phones):
		row = frappe.db.get_value(doctype, name, fields, as_dict=True) or {}
		if not any(_holds_identifier(row.get(field), plan) for field in fields):
			continue
		values = {field: "{}" for field in ("request_data", "response_data") if row.get(field)}
		if row.get("message"):
			values["message"] = content
		_set(doctype, name, values)


def _sweep_event_participants(plan: ErasurePlan, person: str) -> None:
	doctype = "Event Participants"
	if not _exists(doctype) or not _fields(doctype, ("email",)):
		return
	for name in _mentioning(doctype, ("email",), plan.emails, set()):
		if normalize_email(frappe.db.get_value(doctype, name, "email")) in plan.emails:
			frappe.db.set_value(doctype, name, "email", person, update_modified=False)


def _sweep_lead_sync_logs(plan: ErasurePlan, content: str) -> None:
	doctype, fields = "Failed Lead Sync Log", ("lead_data", "traceback")
	if not _exists(doctype):
		return
	fields = _fields(doctype, fields)
	for name in _mentioning(doctype, fields, plan.emails, plan.phones):
		row = frappe.db.get_value(doctype, name, fields, as_dict=True) or {}
		if any(_holds_identifier(row.get(field), plan) for field in fields):
			_wipe(doctype, [name], fields, content)


def _holds_identifier(text: str | None, plan: ErasurePlan) -> bool:
	"""Her email or phone is in `text`, in any formatting (JSON and tracebacks included)."""
	if not text:
		return False
	if scrub_identifiers(text, plan.emails, plan.phones, "\0") != text:
		return True
	# Phone digits with the separators dropped: a whole number, at most a country code before it.
	compact = _SEPARATORS.sub("", text)
	for phone in plan.phones:
		digits = phone_search_digits(phone, PHONE_REGION)
		if digits and re.search(rf"(?<!\d)\d{{0,3}}{re.escape(digits)}(?!\d)", compact):
			return True
	return False


def _sweep_enrichment_runs(records: Targets, content: str) -> None:
	doctype, child = "CRM Enrichment Run", "CRM Enrichment Run Change"
	if not _exists(doctype):
		return
	names = list(_referencing(doctype, "reference_doctype", "reference_name", records))
	if not names:
		return
	runs = frappe.get_all(doctype, filters={"name": ["in", names]}, fields=["name", "reference_doctype"])
	listed = personal_fields()
	for run in runs:
		values = {"raw_json": "{}", "notes": content, "social_profiles": ""}
		_set(doctype, run.name, {field: value for field, value in values.items() if field in _fields(doctype, values)})
		personal = listed.get(run.reference_doctype, set())
		if not personal or not _exists(child):
			continue
		changes = frappe.get_all(
			child,
			filters={"parent": run.name, "parenttype": doctype, "fieldname": ["in", sorted(personal)]},
			pluck="name",
			parent_doctype=doctype,
		)
		for name in changes:
			frappe.db.set_value(child, name, {"old_value": content, "new_value": content}, update_modified=False)


# --- the step -------------------------------------------------------------------------------


def sweep_activities(plan: ErasurePlan, doc: Document, after_commit: list[Callable]) -> None:
	"""Wipe her emails, calls, notes, tasks, comments and files, then the side tables."""
	request = doc.name
	person, content = erased_person(request), erased_content(request)
	records: Targets = {LEAD: plan.leads, CONTACT: plan.contacts, DEAL: plan.deals_on}

	erase_communications(plan.communications, plan.emails, plan.phones, request)
	_queue_reindex(after_commit, "Communication", plan.communications)

	notes = list(dict.fromkeys([*plan.notes, *_sweep_call_logs(plan, doc, person)]))
	_wipe("FCRM Note", notes, ("title", "content"), content)
	_queue_reindex(after_commit, "FCRM Note", notes)
	_wipe("CRM Task", plan.tasks, ("title", "description"), content)

	_wipe("Comment", plan.comments, ("content", "subject"), content)
	_queue_reindex(after_commit, "Comment", plan.comments)
	_sweep_files(plan, records, request, after_commit)
	_reset_comment_caches(records)

	# Rows about her records, her activities or the request itself become C.
	targets: Targets = {
		**records,
		DOCTYPE: [request],
		"Communication": plan.communications,
		"CRM Call Log": plan.call_logs,
		"FCRM Note": notes,
		"CRM Task": plan.tasks,
		"Comment": plan.comments,
	}
	_queue_global_search_removal(after_commit, targets)
	_sweep_notifications(plan, targets, content, person)
	_sweep_notification_logs(plan, targets, content, person)
	_sweep_todos(plan, targets, content, person)
	_sweep_email_queue(plan, targets, content, person)
	_sweep_whatsapp(plan, records, content, person, request, after_commit)
	_sweep_event_participants(plan, person)
	_sweep_lead_sync_logs(plan, content)
	_sweep_enrichment_runs(records, content)
