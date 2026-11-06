# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt
"""Shapes of the erasure registry: entries, how a source is found (finders), what happens to fields

Everything here is data. `discovery_queries` turns each finder kind into one query; phase 03's
executor applies `action` and the field treatments; phase 05 renders the runbook from `found_by`.
"""

from dataclasses import dataclass

# Entry kinds
PERSON, ACTIVITY, FILE, HIDDEN = "person", "activity", "file", "hidden"
KINDS = (PERSON, ACTIVITY, FILE, HIDDEN)

# Entry and match-row actions
SCRUB = "scrub"  # anonymize the listed fields in place, keep the row
REPLACE_CONTENT = "replace_content"  # keep the row, overwrite its content with the marker
DELETE_PERMANENTLY = "delete_permanently"  # delete without a Deleted Document copy (files: after commit)
PURGE = "purge"  # delete the hidden copy outright
FILTER_ENTRIES = "filter_entries"  # Version rows: drop only the entries that carry her data
UNLINK = "unlink"  # shared record (an Address of several people): drop her link row only
REWRITE_COMMENTS = "rewrite_comments"  # `_comments` column: keep `{name}`-only entries
ACTIONS = (SCRUB, REPLACE_CONTENT, DELETE_PERMANENTLY, PURGE, FILTER_ENTRIES, UNLINK, REWRITE_COMMENTS)

# Field treatments (what the executor writes into a listed field)
CLEAR = "clear"  # None
MARKER = "marker"  # content marker: `Content erased <REQ-no>`
NAME_MARKER = "name_marker"  # person-name marker: `Erased <REQ-no>`
REMOVE_ADDRESS = "remove_address"  # drop her addresses from an address list (sender, recipients, cc, bcc)
CLEAR_IF_HERS = "clear_if_hers"  # None, only when the deciding column matches her identifiers
MARKER_IF_HERS = "marker_if_hers"  # name marker, only when the deciding column matches (mandatory)
DELETE_ROWS = "delete_rows"  # child table: delete all rows (Contact Email / Contact Phone)
DROP_HER_LINKS = "drop_her_links"  # Dynamic Link child table: delete rows pointing at her records
TREATMENTS = (
	CLEAR,
	MARKER,
	NAME_MARKER,
	REMOVE_ADDRESS,
	CLEAR_IF_HERS,
	MARKER_IF_HERS,
	DELETE_ROWS,
	DROP_HER_LINKS,
)

# Reference targets: which matched doctypes a reference may point at
SUBJECTS = ("CRM Lead", "CRM Deal", "Contact")
ANY_MATCH = ("*",)


def content_marker(request_name: str) -> str:
	return f"Content erased {request_name}"


def name_marker(request_name: str) -> str:
	return f"Erased {request_name}"


# Finders: each kind is one query builder in discovery_queries.
# `targets` name matched doctypes (or ANY_MATCH); a finder only sees matches found before it runs.


@dataclass(frozen=True)
class Ref:
	"""A dynamic reference pair on the row: (doctype column, name column) pointing at a match"""

	doctype_column: str
	name_column: str
	targets: tuple[str, ...] = SUBJECTS


@dataclass(frozen=True)
class Link:
	"""A Link column on the row pointing at a match of a fixed doctype"""

	column: str
	target: str


@dataclass(frozen=True)
class ChildLink:
	"""Rows of a Dynamic Link-shaped child table (link_doctype/link_name) pointing at a match"""

	child_doctype: str
	targets: tuple[str, ...] = SUBJECTS


@dataclass(frozen=True)
class Backref:
	"""Values of `column` on matched `source` rows that name (or, with `by`, equal a column of) a row"""

	source: str
	column: str
	by: str = "name"


@dataclass(frozen=True)
class ChildBackref:
	"""Dynamic Link rows of a matched `source` whose link_doctype is this entry's doctype"""

	source: str
	child_doctype: str = "Dynamic Link"


@dataclass(frozen=True)
class Emails:
	"""Columns holding one address or an address list, compared exactly (case-insensitive)"""

	columns: tuple[str, ...]
	child_doctype: str | None = None  # the columns live on this child table; its parent matches


@dataclass(frozen=True)
class Phones:
	"""Columns holding a phone number, compared by normalized digits"""

	columns: tuple[str, ...]
	child_doctype: str | None = None


@dataclass(frozen=True)
class Text:
	"""Free text / JSON columns scanned for any identifier (hidden copies)"""

	columns: tuple[str, ...]


@dataclass(frozen=True)
class Entry:
	doctype: str
	kind: str
	found_by: str  # human-readable, rendered into the manual runbook
	action: str
	finders: tuple = ()
	# (fieldname, treatment) the executor changes; *_IF_HERS treatments add the deciding column:
	# (fieldname, treatment, column whose value must match her identifiers)
	fields: tuple[tuple[str, ...], ...] = ()
	keep: tuple[str, ...] = ()  # fields deliberately left as they are
	app: str | None = None  # the app that owns the doctype, when it is optional
	match_rows: bool = True  # False: no match rows; the executor derives the rows from other matches
	table: str | None = None  # a raw table (not a DocType), e.g. `__global_search`
	shared_action: str | None = None  # row action when the row also links to records that are not hers
	filter_doctypes: tuple[str, ...] = ()  # Version: ref doctypes whose rows are filtered, not purged

	@property
	def fieldnames(self) -> tuple[str, ...]:
		return tuple(spec[0] for spec in self.fields)
