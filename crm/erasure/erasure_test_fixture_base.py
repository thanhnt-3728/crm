# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt
"""Marisol fixture building blocks: her identifiers, the fixture record, raw inserts (not a test module)"""

from collections import defaultdict
from dataclasses import dataclass, field

import frappe
from frappe.utils import now

from crm.fcrm.doctype.crm_erasure_request.erasure_test_fixtures import REP, as_user

HER_EMAILS = ("marisol.reyes@example.net", "M.Reyes@example.net")
HER_PHONES = ("+1 (415) 555-0123", "+1 415-555-0177")  # as the rep types them: with country code
HER_PHONE_DATA = ("(415) 555-0123", "+1 415-555-0177")  # as stored on her records
HER_IMAGE_URL = "/files/marisol-portrait.png"
COLLEAGUE_EMAIL, COLLEAGUE_PHONE = "kai.colleague@example.net", "+1 415-555-0199"
NEAR_EMAIL, NEAR_PHONE = "jomarisol.reyes@example.net", "(415) 555-0124"  # superstring / one digit off
REP_PHONE = "+1 415-555-0100"
OPEN_STATUS, WON_STATUS = "Erasure Test Negotiation", "Erasure Test Won"
ERROR_LOG_METHOD = "erasure-test-fixture"  # tags fixture Error Log rows (MyISAM, not rolled back)

EXPECTED, HIDDEN, NEAR_MISSES = "expected", "hidden", "near_misses"


@dataclass
class MarisolFixture:
	lead: str = ""
	contact: str = ""
	deal_won: str = ""
	deal_open: str = ""
	colleague_contact: str = ""
	colleague_deal: str = ""
	expected: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))  # match rows
	hidden: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))  # hidden copies
	near_misses: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
	names: dict[str, str] = field(default_factory=dict)  # label -> doc name, for targeted assertions

	def add(self, bucket: str, label: str, doc) -> str:
		"""Record `doc` under `bucket` (EXPECTED, HIDDEN or NEAR_MISSES) and `label`; returns its name"""
		name = str(doc.name)  # autoincrement doctypes (CRM Task) have int names; matches store strings
		getattr(self, bucket)[doc.doctype].add(name)
		self.names[label] = name
		return name

	def seed(self, bucket: str, label: str, doctype: str, **values) -> str:
		"""Raw-insert a row of `doctype` and record it"""
		return self.add(bucket, label, raw_insert({"doctype": doctype, **values}))


def raw_insert(values: dict, owner: str = REP):
	"""Insert a row and its child rows without hooks or validation (fixture data only)"""
	doc = frappe.get_doc(values)
	stamp = now()
	for row in (doc, *doc.get_all_children()):
		if row is not doc:
			row.parent, row.parenttype = doc.name, doc.doctype
		if not row.name:
			row.set_new_name()  # naming rule of the doctype (hash, series, field or autoincrement)
		row.owner = row.modified_by = owner
		row.creation = row.modified = stamp
		row.db_insert()
	return doc


def insert_as(user: str, values: dict):
	"""A real insert (hooks run) as `user`, ignoring permissions"""
	with as_user(user):
		return frappe.get_doc(values).insert(ignore_permissions=True)
