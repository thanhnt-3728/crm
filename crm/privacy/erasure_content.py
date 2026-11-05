"""Erasing the person's content (spec 5.6): emails, calls, notes, tasks, comments, files,
WhatsApp messages, and the other places that hold the person's text or details.

The records stay so activity history keeps its shape. Their text becomes the content
placeholder (`Content erased PDR-0001`); the person's addresses, numbers and names inside
other text become the person placeholder (`Erased person PDR-0001`). Other people's
addresses and numbers on the same records are left as they are.

Nothing here calls `doc.save()`: writes go through `frappe.db.set_value(...,
update_modified=False)`, `frappe.db.delete` and `frappe.delete_doc(...,
delete_permanently=True)`. Files leave the disk, and the search index is updated, only after
the transaction commits (`frappe.db.after_commit`), so a rolled-back erasure leaves both as
they were.

The text helpers at the top do not need a site.
"""

import json
import re
from contextlib import contextmanager

import frappe
import phonenumbers
from phonenumbers import NumberParseException
from pypika import Criterion
from pypika.functions import Function, Lower

from crm.privacy import personal_fields
from crm.privacy.erasure import (
	_DealVersionMatcher,
	_Person,
	_scannable_phones,
	_version_tables,
	placeholder_content,
	placeholder_person,
	scrub_version_data,
)
from crm.privacy.identifiers import extract_emails, normalize_email, text_contains_email, text_contains_phone
from crm.privacy.matching import _wildcard_digits
from crm.utils import normalize_phone

# Characters allowed between the digits of a phone number typed in text.
PHONE_SEPARATOR = r"[\s().\-/]{0,3}"

# Fields holding an email's text, wiped to the content placeholder.
COMMUNICATION_TEXT_FIELDS = ("subject", "content", "text_content")
COMMUNICATION_HEADERS = ("sender", "recipients", "cc", "bcc")

# Versions of these doctypes outside the erased records can still name the person (a deal
# she was removed from, say): only her values in them are replaced.
HISTORY_DOCTYPES = ("CRM Lead", "CRM Deal", "Contact")

# WhatsApp message fields that hold the message or its media, besides `message`.
WA_MEDIA_FIELDS = ("attach", "media_url", "template_body_parameters", "template_header_parameters")


# -- Text helpers (no site needed) ---------------------------------------------------------


def split_person_values(values) -> tuple[set[str], set[str], set[str]]:
	"""(emails, phones, names) out of `erase_person_values`: emails hold an @, phones are
	normalized (+ and digits), and everything else is a name."""
	emails, phones, names = set(), set(), set()
	for value in values or ():
		value = (value or "").strip()
		if not value:
			continue
		if "@" in value:
			emails.add(normalize_email(value))
		elif value.startswith("+") and value[1:].isdigit():
			phones.add(value)
		else:
			names.add(value)
	return emails, phones, names


def _split_header(header: str) -> list[str]:
	"""The entries of an address header such as `"Vega, Marisol" <m@x.net>; bob@x.net`,
	split on commas and semicolons outside quotes and angle brackets."""
	entries, current = [], []
	quoted = bracketed = escaped = False
	for char in header:
		if escaped:
			escaped = False
		elif char == "\\" and quoted:
			escaped = True
		elif char == '"':
			quoted = not quoted
		elif char == "<" and not quoted:
			bracketed = True
		elif char == ">" and not quoted:
			bracketed = False
		elif char in ",;" and not quoted and not bracketed:
			entries.append("".join(current))
			current = []
			continue
		current.append(char)
	entries.append("".join(current))
	return [entry.strip() for entry in entries if entry.strip()]


def replace_addresses(header: str | None, emails: set[str], placeholder: str) -> str | None:
	"""`header` (sender, recipients, cc or bcc) with each entry whose address is one of the
	normalized `emails` replaced by `placeholder`, whatever its case or display name. Other
	entries are kept as written. Unchanged when no entry is the person's."""
	if not header or not emails:
		return header
	entries, changed = [], False
	for entry in _split_header(header):
		if set(extract_emails(entry)) & emails:
			changed = True
			if placeholder not in entries:
				entries.append(placeholder)
		else:
			entries.append(entry)
	return ", ".join(entries) if changed else header


def phone_parts(phone: str) -> tuple[str, str]:
	"""(country code, national number digits) of a normalized phone; ("", all digits) when
	it is not a valid number."""
	try:
		parsed = phonenumbers.parse(phone, None)
		if phonenumbers.is_valid_number(parsed):
			return str(parsed.country_code), str(parsed.national_number)
	except NumberParseException:
		pass
	return "", re.sub(r"\D", "", phone or "")


def _phone_pattern(country_code: str, digits: str) -> re.Pattern:
	"""The phone as typed in text: its digits with spaces, dots, dashes, slashes or
	brackets between them, with or without the country code."""
	body = PHONE_SEPARATOR.join(digits)
	prefix = rf"(?:(?:\+|00)?{country_code}{PHONE_SEPARATOR})?" if country_code else ""
	return re.compile(rf"(?<![\d+]){prefix}\(?{body}(?!\d)")


def _digits(text: str) -> str:
	return re.sub(r"\D", "", text)


def replace_person_text(text: str | None, emails, phones, names, person: str, content: str) -> str | None:
	"""`text` with the person's values replaced by `person`: `emails` (normalized) in any
	case, `phones` (as `phone_parts`) however they are typed, and `names` as whole words in
	any case. When a phone's digits are in the text but not in a form that can be cut out,
	the whole text becomes `content`."""
	if not text or not isinstance(text, str):
		return text
	out = text
	for email in sorted(emails, key=len, reverse=True):
		pattern = rf"(?<![\w.%+-]){re.escape(email)}(?![\w-]|\.[\w-])"
		out = re.sub(pattern, lambda _match: person, out, flags=re.IGNORECASE)
	for country_code, digits in phones:
		if not digits or digits not in _digits(out):
			continue
		out = _phone_pattern(country_code, digits).sub(lambda _match: person, out)
		if digits in _digits(out):
			return content
	for name in sorted(names, key=len, reverse=True):
		pattern = rf"(?<!\w){re.escape(name)}(?!\w)"
		out = re.sub(pattern, lambda _match: person, out, flags=re.IGNORECASE)
	return out


# -- Reading the person's values -----------------------------------------------------------


class _Who:
	"""The person's values, split by kind, from `erase_person_values`."""

	def __init__(self, person_values):
		self.emails, self.phones, self.names = split_person_values(person_values)
		# Phones too short to look for in free text are left out of text scans.
		self.text_phones = _scannable_phones(sorted(self.phones))
		self.phone_parts = [phone_parts(phone) for phone in self.text_phones]
		self.person = _Person(
			emails=set(self.emails),
			phones=set(self.phones),
			names=set(self.names),
			full_names={name.casefold() for name in self.names},
		)

	@property
	def full_names(self) -> set[str]:
		"""Names of two words or more (first + last, a full lead or contact name, a requester
		name). A single first or last name may well be someone else's, so it is not looked
		for in text."""
		return {name for name in self.names if len(name.split()) >= 2}

	def in_text(self, text) -> bool:
		"""Whether `text` contains one of the person's emails or phones."""
		if not text:
			return False
		text = str(text)
		return any(text_contains_email(text, email) for email in self.emails) or any(
			text_contains_phone(text, phone) for phone in self.text_phones
		)

	def like_conditions(self, column) -> list:
		"""SQL prefilters for `in_text` on `column`: a superset of the matches."""
		conditions = [Lower(column).like(f"%{email}%") for email in sorted(self.emails)]
		patterns = [pattern for pattern in map(_wildcard_digits, self.text_phones) if pattern]
		return conditions + [column.like(pattern) for pattern in patterns]


def _lower_trim(column):
	return Function("LOWER", Function("TRIM", column))


# -- The eraser ----------------------------------------------------------------------------


class _ContentEraser:
	def __init__(self, request_name: str, person_values):
		self.request_name = request_name
		self.person = placeholder_person(request_name)
		self.content = placeholder_content(request_name)
		self.who = _Who(person_values)
		# Names replaced inside free text: full names only (see `_Who.full_names`), plus the
		# old names of her renamed contacts once `erase_content` knows them.
		self.text_names = self.who.full_names
		self.reindex: set[tuple[str, str]] = set()
		self.deleted_files: list[dict] = []

	def replace(self, text, names=True):
		return replace_person_text(
			text,
			self.who.emails,
			self.who.phone_parts,
			self.text_names if names else (),
			self.person,
			self.content,
		)

	def rows_naming(self, doctype: str, columns, fields) -> list[dict]:
		"""Rows of `doctype` whose `columns` contain one of the person's emails or phones."""
		table = frappe.qb.DocType(doctype)
		conditions = [c for column in columns for c in self.who.like_conditions(table[column])]
		if not conditions:
			return []
		rows = (
			frappe.qb.from_(table)
			.select(*[table[f] for f in fields])
			.where(Criterion.any(conditions))
			.run(as_dict=True)
		)
		return [row for row in rows if any(self.who.in_text(row.get(column)) for column in columns)]

	def set_text(self, doctype: str, names, fields) -> None:
		"""Set `fields` of the `names` records to the content placeholder."""
		if not names:
			return
		meta = frappe.get_meta(doctype)
		values = {field: self.content for field in fields if meta.has_field(field)}
		if values:
			frappe.db.set_value(doctype, {"name": ["in", list(names)]}, values, update_modified=False)

	# -- Emails ------------------------------------------------------------------------

	def communications(self, names) -> None:
		"""Subject and body → content placeholder; each of the person's addresses in the
		headers → person placeholder; the email's attachments deleted. Never deleted."""
		if not names:
			return
		meta = frappe.get_meta("Communication")
		headers = [f for f in COMMUNICATION_HEADERS if meta.has_field(f)]
		extra = [f for f in ("sender_full_name", "phone_no") if meta.has_field(f)]
		text = {f: self.content for f in COMMUNICATION_TEXT_FIELDS if meta.has_field(f)}
		rows = frappe.get_all(
			"Communication", filters={"name": ["in", list(names)]}, fields=["name", *headers, *extra]
		)
		for row in rows:
			values = dict(text)
			for field in headers:
				new = replace_addresses(row.get(field), self.who.emails, self.person)
				if new != row.get(field):
					values[field] = new
			if "sender_full_name" in extra and set(extract_emails(row.get("sender"))) & self.who.emails:
				values["sender_full_name"] = self.person
			if (
				"phone_no" in extra
				and row.get("phone_no")
				and normalize_phone(row.phone_no) in self.who.phones
			):
				values["phone_no"] = self.person
			frappe.db.set_value("Communication", row.name, values, update_modified=False)
			self.reindex.add(("Communication", row.name))

		attached = frappe.get_all(
			"File",
			filters={"attached_to_doctype": "Communication", "attached_to_name": ["in", list(names)]},
			pluck="name",
		)
		self.delete_files(attached)

	# -- Calls, notes, tasks, comments -------------------------------------------------

	def call_logs(self, names) -> bool:
		"""The person's number → person placeholder, recording link cleared. Returns whether
		any call had a recording."""
		if not names:
			return False
		table = frappe.qb.DocType("CRM Call Log")
		rows = (
			frappe.qb.from_(table)
			.select(table.name, table["from"], table["to"], table.recording_url)
			.where(table.name.isin(list(names)))
			.run(as_dict=True)
		)
		recordings = False
		for row in rows:
			values = {}
			for field in ("from", "to"):
				if row[field] and normalize_phone(row[field]) in self.who.phones:
					values[field] = self.person
			if row.recording_url:
				values["recording_url"] = ""
				recordings = True
			if values:
				frappe.db.set_value("CRM Call Log", row.name, values, update_modified=False)
		return recordings

	def notes(self, names) -> None:
		self.set_text("FCRM Note", names, ("title", "content"))
		self.reindex.update(("FCRM Note", name) for name in names)
		# Notes keep change history: their old titles and texts go too.
		versions = (
			frappe.get_all(
				"Version",
				filters={"ref_doctype": "FCRM Note", "docname": ["in", list(names)]},
				fields=["name", "data"],
			)
			if names
			else []
		)
		for version in versions:
			self.write_version(version, {"title", "content"}, self.content)

	def tasks(self, names) -> None:
		# Status, dates and assignee stay.
		self.set_text("CRM Task", names, ("title", "description"))
		self.reindex.update(("CRM Task", name) for name in names)

	def comments(self, names) -> None:
		self.set_text("Comment", names, ("content",))
		self.reindex.update(("Comment", name) for name in names)

	def todos(self, erased: dict) -> None:
		"""Assignments on the erased records describe them (often by the person's name)."""
		for doctype, names in erased.items():
			if names:
				frappe.db.set_value(
					"ToDo",
					{"reference_type": doctype, "reference_name": ["in", list(names)]},
					"description",
					self.content,
					update_modified=False,
				)

	def comment_caches(self, erased: dict) -> None:
		"""A record's `_comments` keeps the text of its latest comments for list views."""
		for doctype, names in erased.items():
			if not names:
				continue
			rows = frappe.get_all(
				doctype,
				filters={"name": ["in", list(names)], "_comments": ["is", "set"]},
				fields=["name", "_comments"],
			)
			for row in rows:
				try:
					entries = json.loads(row._comments)
				except ValueError:
					entries = []
				if not isinstance(entries, list):
					entries = []
				for entry in entries:
					if isinstance(entry, dict) and "comment" in entry:
						entry["comment"] = self.content
				frappe.db.set_value(
					doctype, row.name, "_comments", json.dumps(entries), update_modified=False
				)

	# -- Files ---------------------------------------------------------------------------

	def delete_files(self, names) -> None:
		"""Delete the File records now (no Deleted Document copy, no "attachment removed"
		comment naming the file) and their content on disk after commit."""
		if not names:
			return
		rows = frappe.get_all(
			"File",
			filters={"name": ["in", list(names)], "is_folder": 0},
			fields=["name", "file_name", "file_url", "thumbnail_url", "is_private", "content_hash"],
		)
		if not rows:
			return
		frappe.db.delete("File", {"name": ["in", [row.name for row in rows]]})
		self.deleted_files.extend(rows)

	# -- WhatsApp ------------------------------------------------------------------------

	def whatsapp(self, names, profiles) -> None:
		"""Messages → content placeholder, media cleared; the person's WhatsApp profiles
		(`targets.wa_profiles`, the ones the approval screen listed) deleted, and messages
		no longer point at them."""
		if not frappe.db.table_exists("WA Message"):
			return
		meta = frappe.get_meta("WA Message")
		if names:
			values = {"message": self.content}
			values.update({field: None for field in WA_MEDIA_FIELDS if meta.has_field(field)})
			frappe.db.set_value("WA Message", {"name": ["in", list(names)]}, values, update_modified=False)

		profiles = sorted(profiles or [])
		if not profiles:
			return
		frappe.db.set_value("WA Message", {"to": ["in", profiles]}, "to", None, update_modified=False)
		for profile in profiles:
			frappe.delete_doc(
				"WA Profile", profile, delete_permanently=True, ignore_permissions=True, force=True
			)

	# -- Other places --------------------------------------------------------------------

	def notifications(self, erased: dict, content: dict) -> None:
		"""Notifications about the erased records or content, or naming the person's email or
		phone: the person's values in their text → person placeholder. A notification that
		copies erased content (a mention in a comment, say) has that text wiped."""
		fields = [
			"name",
			"message",
			"notification_text",
			"notification_type_doctype",
			"notification_type_doc",
		]
		copies = {(doctype, name) for doctype, names in content.items() for name in names}

		names = set()
		for doctype, records in {**erased, **content}.items():
			if not records:
				continue
			for doctype_field, name_field in (
				("reference_doctype", "reference_name"),
				("notification_type_doctype", "notification_type_doc"),
			):
				names.update(
					frappe.get_all(
						"CRM Notification",
						filters={doctype_field: doctype, name_field: ["in", list(records)]},
						pluck="name",
					)
				)
		rows = {
			row.name: row
			for row in self.rows_naming("CRM Notification", ("message", "notification_text"), fields)
		}
		if names - set(rows):
			for row in frappe.get_all(
				"CRM Notification", filters={"name": ["in", sorted(names - set(rows))]}, fields=fields
			):
				rows[row.name] = row

		for row in rows.values():
			values = {"message": self.replace(row.message)}
			if (row.notification_type_doctype, row.notification_type_doc) in copies:
				values["notification_text"] = self.content
			else:
				values["notification_text"] = self.replace(row.notification_text)
			values = {field: value for field, value in values.items() if value != row.get(field)}
			if values:
				frappe.db.set_value("CRM Notification", row.name, values, update_modified=False)

	def email_queue(self) -> None:
		"""Queued emails to the person are deleted (they hold the whole message)."""
		if not self.who.emails:
			return
		table = frappe.qb.DocType("Email Queue Recipient")
		rows = (
			frappe.qb.from_(table)
			.select(table.parent, table.recipient)
			.where(
				Criterion.any(
					[Lower(table.recipient).like(f"%{email}%") for email in sorted(self.who.emails)]
				)
			)
			.run(as_dict=True)
		)
		queued = {row.parent for row in rows if set(extract_emails(row.recipient)) & self.who.emails}
		for name in sorted(queued):
			if frappe.db.exists("Email Queue", name):
				frappe.delete_doc("Email Queue", name, delete_permanently=True, ignore_permissions=True)

	def event_participants(self) -> None:
		if not self.who.emails or not frappe.db.has_column("Event Participants", "email"):
			return
		table = frappe.qb.DocType("Event Participants")
		(
			frappe.qb.update(table)
			.set(table.email, self.person)
			.where(_lower_trim(table.email).isin(sorted(self.who.emails)))
		).run()

	def lead_sync_logs(self) -> None:
		"""Failed Facebook lead syncs keep the lead's data as JSON."""
		if not frappe.db.table_exists("Failed Lead Sync Log"):
			return
		for row in self.rows_naming(
			"Failed Lead Sync Log", ("lead_data", "traceback"), ["name", "lead_data", "traceback"]
		):
			values = {}
			if self.who.in_text(row.lead_data):
				values["lead_data"] = self.content
			traceback = self.replace(row.traceback)
			if traceback != row.traceback:
				values["traceback"] = traceback
			if values:
				frappe.db.set_value("Failed Lead Sync Log", row.name, values, update_modified=False)

	def enrichment_runs(self) -> None:
		"""A change an enrichment run recorded with the person's email or phone in it: that
		value → person placeholder. The run's raw data has the person's values replaced."""
		if frappe.db.table_exists("CRM Enrichment Run Change"):
			columns = ("old_value", "new_value")
			for row in self.rows_naming("CRM Enrichment Run Change", columns, ["name", *columns]):
				values = {column: self.person for column in columns if self.who.in_text(row.get(column))}
				frappe.db.set_value("CRM Enrichment Run Change", row.name, values, update_modified=False)
		if frappe.db.table_exists("CRM Enrichment Run"):
			columns = ("raw_json", "social_profiles", "notes")
			for row in self.rows_naming("CRM Enrichment Run", columns, ["name", *columns]):
				# Company data: names are not replaced, they may be a business's.
				values = {column: self.replace(row.get(column), names=False) for column in columns}
				values = {column: value for column, value in values.items() if value != row.get(column)}
				if values:
					frappe.db.set_value("CRM Enrichment Run", row.name, values, update_modified=False)

	def retitle_links(self, child: str, parenttype: str | None, leads=(), contacts=()) -> None:
		"""Link rows to the person's leads or contacts keep the record's title (the person's
		name) in `link_title`; replace it."""
		table = frappe.qb.DocType(child)
		conditions = []
		if leads:
			conditions.append((table.link_doctype == "CRM Lead") & table.link_name.isin(list(leads)))
		if contacts:
			conditions.append((table.link_doctype == "Contact") & table.link_name.isin(list(contacts)))
		if not conditions:
			return
		query = frappe.qb.update(table).set(table.link_title, self.person).where(Criterion.any(conditions))
		if parenttype:
			query = query.where(table.parenttype == parenttype)
		query.run()

	# -- History outside the erased records (R10) --------------------------------------

	def write_version(self, version, fields, placeholder, tables=None, renames=None, matcher=None) -> None:
		try:
			data = json.loads(version.data or "{}")
		except ValueError:
			return
		if not isinstance(data, dict):
			return
		scrubbed = scrub_version_data(data, fields, placeholder, tables, renames, matcher)
		if scrubbed != data:
			frappe.db.set_value(
				"Version",
				version.name,
				"data",
				frappe.as_json(scrubbed, indent=None, separators=(",", ":")),
				update_modified=False,
			)

	def other_versions(self, targets) -> None:
		"""The history of leads, deals and contacts that were not erased but hold the
		person's data: deals she was removed from, and records whose history holds her email,
		phone or a link to her contact. Her contacts rows (by contact, email or phone) and her
		emails and phones are replaced; links to her contact inside her rows are renamed.

		Her names are replaced only on the deals she was removed from (tied to her by the
		request). Elsewhere a value equal to one of her names may be a namesake's, so it
		stays."""
		renames = dict(targets.renames or {})
		erased = {
			"CRM Lead": set(targets.leads),
			"CRM Deal": set(targets.deals_still_on),
			"Contact": set(targets.contacts),
		}
		removed_from = set(targets.deals_removed_from)
		table = frappe.qb.DocType("Version")
		conditions = self.who.like_conditions(table.data)
		conditions += [table.data.like(f'%"{old}"%') for old in sorted(renames)]
		if targets.deals_removed_from:
			conditions.append(
				(table.ref_doctype == "CRM Deal") & table.docname.isin(list(targets.deals_removed_from))
			)
		if not conditions:
			return
		versions = (
			frappe.qb.from_(table)
			.select(table.name, table.ref_doctype, table.docname, table.data)
			.where(table.ref_doctype.isin(HISTORY_DOCTYPES))
			.where(Criterion.any(conditions))
			.run(as_dict=True)
		)
		contacts = set(targets.contacts) | {old for old, new in renames.items() if new in targets.contacts}
		tied = _DealVersionMatcher(self.who.person, contacts, set())
		untied = _DealVersionMatcher(self.who.person, contacts, set(), names=False)
		for version in versions:
			if version.docname in erased[version.ref_doctype]:
				continue  # scrubbed with the record
			is_tied = version.ref_doctype == "CRM Deal" and version.docname in removed_from
			self.write_version(
				version,
				personal_fields(version.ref_doctype),
				self.person,
				_version_tables(version.ref_doctype),
				renames,
				tied if is_tied else untied,
			)

	# -- After commit --------------------------------------------------------------------

	def after_commit(self) -> None:
		files, pairs = list(self.deleted_files), sorted(self.reindex)
		self.deleted_files, self.reindex = [], set()
		if files or pairs:
			work = _AfterCommitWork(files, pairs)
			frappe.db.after_commit.add(work)
			tracked = frappe.flags.privacy_after_commit_work
			if isinstance(tracked, list):
				tracked.append(work)


# -- After commit --------------------------------------------------------------------------


class _AfterCommitWork:
	"""What waits for the commit: removing deleted files from disk and re-indexing. Runs
	once; does nothing once cancelled (the erasure was rolled back); never raises."""

	def __init__(self, files: list[dict], pairs: list[tuple[str, str]]):
		self.files = files
		self.pairs = pairs
		self.state = "pending"

	def __call__(self) -> None:
		if self.state != "pending":
			return
		self.state = "done"
		_remove_from_disk(self.files)
		try:
			_reindex(self.pairs)
		except Exception:
			frappe.log_error(title="Erasure: re-indexing failed")

	def cancel(self) -> None:
		if self.state == "pending":
			self.state = "cancelled"


@contextmanager
def tracked_after_commit_work():
	"""Keep the after-commit work registered inside the block, for
	`cancel_after_commit_work` and `run_after_commit_work`."""
	previous = frappe.flags.privacy_after_commit_work
	frappe.flags.privacy_after_commit_work = []
	try:
		yield
	finally:
		frappe.flags.privacy_after_commit_work = previous


def _tracked_work() -> list:
	return list(frappe.flags.privacy_after_commit_work or [])


def cancel_after_commit_work() -> None:
	"""The erasure was rolled back: its queued file removal and re-indexing must not run,
	whether or not the rollback cleared Frappe's after-commit queue."""
	for work in _tracked_work():
		work.cancel()


def run_after_commit_work() -> None:
	"""Run the tracked work that has not run yet (another after-commit callback failed
	before it, and the queue was cleared)."""
	for work in _tracked_work():
		work()


def _remove_from_disk(rows) -> None:
	"""Remove deleted files' content, unless another File record still uses it."""
	for row in rows:
		try:
			url = row.get("file_url") or ""
			if url.startswith(("http://", "https://")):
				continue  # not stored here
			shared = bool(url and frappe.db.exists("File", {"file_url": url})) or bool(
				row.get("content_hash") and frappe.db.exists("File", {"content_hash": row.content_hash})
			)
			file = frappe.get_doc({"doctype": "File", **row})
			file.delete_file_data_content(only_thumbnail=shared)
		except Exception:
			frappe.log_error(title=f"Erasure: could not remove file {row.get('name')} from disk")


def _reindex(pairs) -> None:
	"""Re-index the changed records the CRM search indexes (today: emails, notes and
	comments; leads, deals, contacts and tasks are passed in case they are added)."""
	try:
		from crm.search_sqlite import CRMSearch

		indexed = set(CRMSearch.INDEXABLE_DOCTYPES)
		search = CRMSearch()
	except Exception:
		frappe.log_error(title="Erasure: search index unavailable")
		return
	for doctype, name in pairs:
		if doctype in indexed:
			search.index_doc(doctype, name)  # logs its own errors


# -- Entry points ----------------------------------------------------------------------------


def erase_communications(names: list[str], request_name: str, person_values: set[str]) -> None:
	"""Wipe the emails `names`: subject and body → `Content erased {request}`, each of the
	person's addresses in sender/recipients/cc/bcc → `Erased person {request}` (other
	addresses kept), attachments deleted. The emails themselves are never deleted."""
	eraser = _ContentEraser(request_name, person_values)
	eraser.communications(names)
	eraser.after_commit()


def erase_content(request, targets, person_values: set[str]) -> None:
	"""Erase everything in `targets` besides the records `erase_records` handles. Run after
	`erase_records` (it reads the new contact names and `targets.renames`), with the
	`person_values` read before it. Sets `targets.recordings_present` when a call had a
	recording."""
	eraser = _ContentEraser(request.name, person_values)
	old_contacts = {old for old, new in (targets.renames or {}).items() if new in targets.contacts}
	eraser.text_names = eraser.who.full_names | old_contacts
	erased = targets.erased_records()
	content = {
		"Communication": targets.communications,
		"CRM Call Log": targets.call_logs,
		"FCRM Note": targets.notes,
		"CRM Task": targets.tasks,
		"Comment": targets.comments,
		"WA Message": targets.wa_messages,
	}

	eraser.communications(targets.communications)
	if eraser.call_logs(targets.call_logs):
		targets.recordings_present = True
	eraser.notes(targets.notes)
	eraser.tasks(targets.tasks)
	eraser.comments(targets.comments)
	eraser.todos(erased)
	eraser.comment_caches(erased)
	eraser.delete_files(targets.files)
	eraser.whatsapp(targets.wa_messages, targets.wa_profiles)

	eraser.notifications(erased, content)
	eraser.email_queue()
	eraser.event_participants()
	eraser.lead_sync_logs()
	eraser.enrichment_runs()

	eraser.retitle_links("Dynamic Link", None, leads=targets.leads)
	eraser.retitle_links(
		"Communication Link", "Communication", leads=targets.leads, contacts=targets.contacts
	)
	eraser.other_versions(targets)

	eraser.reindex.update(("CRM Lead", name) for name in targets.leads)
	eraser.reindex.update(("CRM Deal", name) for name in targets.deals_still_on)
	eraser.reindex.update(("Contact", name) for name in targets.contacts)
	eraser.after_commit()
