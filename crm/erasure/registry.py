# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt
"""The erasure registry: where her data lives and what happens to it (one place to add a source)

REGISTRY is ordered: an entry only sees matches of entries before it (the four subject entries
are resolved together first), and the executor applies the entries in the same order. Hidden
copies are counted in the preview and purged (or filtered) by the executor, never listed as rows.
"""

from crm.erasure.registry_activity_entries import ACTIVITY_ENTRIES, WHATSAPP
from crm.erasure.registry_model import (
	ANY_MATCH,
	FILTER_ENTRIES,
	HIDDEN,
	PURGE,
	REWRITE_COMMENTS,
	Emails,
	Entry,
	Link,
	Ref,
	Text,
)
from crm.erasure.registry_subject_entries import SUBJECT_ENTRIES

HIDDEN_ENTRIES = (
	Entry(
		doctype="Version",
		kind=HIDDEN,
		found_by=(
			"Change history of any match, or whose data mentions her identifiers. Purged; rows of CRM Deal "
			"and of records that are not matches are filtered (entries naming her fields or identifiers dropped)"
		),
		action=PURGE,
		filter_doctypes=("CRM Deal",),
		finders=(Ref("ref_doctype", "docname", ANY_MATCH), Text(("data",))),
	),
	Entry(
		doctype="Deleted Document",
		kind=HIDDEN,
		found_by="Copies of deleted records whose data mentions her identifiers",
		action=PURGE,
		finders=(Text(("data",)),),
	),
	Entry(
		doctype="__global_search",
		table="__global_search",
		kind=HIDDEN,
		found_by="Search index rows of any match, or whose content mentions her identifiers. Deleted, then re-indexed",
		action=PURGE,
		finders=(Ref("doctype", "name", ANY_MATCH), Text(("content",))),
	),
	Entry(
		doctype="Email Queue",
		kind=HIDDEN,
		found_by="Queued emails to her address, or referencing a match or one of her Communications (with recipients)",
		action=PURGE,
		finders=(
			Ref("reference_doctype", "reference_name", ANY_MATCH),
			Link("communication", "Communication"),
			Emails(("recipient",), child_doctype="Email Queue Recipient"),
		),
	),
	Entry(
		doctype="WA Log",
		kind=HIDDEN,
		app=WHATSAPP,
		found_by="WhatsApp webhook logs referencing a match, or whose payload or message mentions her identifiers",
		action=PURGE,
		finders=(
			Ref("reference_doctype", "reference_docname", ANY_MATCH),
			Text(("message", "request_data", "response_data", "traceback")),
		),
	),
	Entry(
		doctype="Error Log",
		kind=HIDDEN,
		found_by="Error logs referencing a match, or whose error text mentions her identifiers",
		action=PURGE,
		finders=(Ref("reference_doctype", "reference_name", ANY_MATCH), Text(("error", "method"))),
	),
	Entry(
		doctype="_comments",
		table="_comments",
		kind=HIDDEN,
		found_by="The _comments cache column of her Lead, Deal and Contact rows, rewritten to name-only entries",
		action=REWRITE_COMMENTS,
		match_rows=False,
	),
)

REGISTRY: tuple[Entry, ...] = (*SUBJECT_ENTRIES, *ACTIVITY_ENTRIES, *HIDDEN_ENTRIES)

# Fields the executor changes per doctype; phase 03 drops Version entries naming them
PERSON_FIELDS: dict[str, frozenset[str]] = {
	entry.doctype: frozenset(entry.fieldnames) for entry in REGISTRY if entry.fields and not entry.table
}

# Recorded on every executed request (`known_limitations`) and in the manual runbook
KNOWN_LIMITATIONS = (
	"Database backups and binary logs keep her data until they rotate out (backups are out of scope).",
	"Emails already delivered to mailboxes outside the CRM and WhatsApp chats on phones cannot be recalled.",
	"Her name alone never matches: a record that mentions only her name, with no link to her records "
	"and none of her emails or phones, is not found.",
	"Text that spells an identifier unusually (an address split across lines, a number written in words "
	"with more than three separators between digit groups, or with its last four digits split) is not "
	"found by discovery.",
	"Files are matched by what they are attached to, not by their content. A file on disk shared with a "
	"record that is not hers (uploads are deduplicated by content) is kept; only her File rows go.",
	"A phone identifier without an extension matches that number with any extension (a colleague on "
	"the same switchboard number); give the extension when the number is shared.",
	"An Email Queue row is purged whole when any of its recipients is hers, including the copies "
	"queued for other recipients of the same email.",
	"Copies held by other systems (ERPNext customer sync, the telephony provider's recordings, the email "
	"provider) are not erased by the CRM.",
	"The final residual check reads phone numbers as digits only, so unrelated digits that happen to run "
	"together into her number in a long text block stop the erasure with an error naming the table; it "
	"needs a manual look before the job is run again.",
	"If an erasure run fails and is rolled back, the Error Log rows it purged stay deleted (that table "
	"does not take part in transactions); search index rows are rebuilt.",
	"A Lead, Deal or Contact form left open during the erasure is told to reload, but saving it without "
	"reloading writes the old values back; run the erasure again after such a save.",
	"Queued email bodies encoded as base64 (attachments, some HTML mail) are not read for her address; "
	"queued mail to her or about her records is purged by recipient and reference.",
	"Renaming her Contact and Address away from her name clears the site cache once, so the CRM is a "
	"little slower for a moment after the erasure.",
)


def entry_for(doctype: str) -> Entry:
	"""The registry entry for `doctype`; KeyError when it is not registered"""
	for entry in REGISTRY:
		if entry.doctype == doctype:
			return entry
	raise KeyError(doctype)


def registry_position(doctype: str) -> int:
	"""Index of `doctype` in REGISTRY (match rows are ordered by it); unknown doctypes sort last"""
	for index, entry in enumerate(REGISTRY):
		if entry.doctype == doctype:
			return index
	return len(REGISTRY)
