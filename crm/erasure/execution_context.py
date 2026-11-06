# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt
"""What one execution works from (the approved matches) and what it changed (counts, no identifiers)"""

from collections import defaultdict
from dataclasses import dataclass, field

import frappe

from crm.erasure.identifiers import Identifiers
from crm.erasure.registry_model import SUBJECTS


@dataclass
class Changes:
	counts: dict[str, int] = field(default_factory=lambda: defaultdict(int))  # doctype -> rows changed
	docs: list[str] = field(default_factory=list)  # names of her person records that changed
	files: list[str] = field(default_factory=list)  # disk file URLs deleted after the commit
	reindex: list[tuple[str, str]] = field(default_factory=list)  # re-indexed after the commit
	renamed: list[tuple[str, str, str]] = field(default_factory=list)  # (doctype, old, new)
	skipped: dict[str, int] = field(default_factory=lambda: defaultdict(int))  # left as is (unreadable)

	def add(self, doctype: str, count: int = 1) -> None:
		if count:
			self.counts[doctype] += count

	@property
	def total(self) -> int:
		return sum(self.counts.values())


@dataclass(frozen=True)
class Context:
	request_name: str
	ids: Identifiers
	matches: dict[str, frozenset[str]]  # non-excluded matches: doctype -> names
	excluded: frozenset[tuple[str, str]]  # (doctype, name) the request leaves untouched
	actions: dict[tuple[str, str], str]  # match row action (scrub / unlink / ...)

	@property
	def her_records(self) -> set[tuple[str, str]]:
		"""Her Lead, Deal and Contact records (link rows pointing at these are hers)"""
		return {(doctype, name) for doctype in SUBJECTS for name in self.matches.get(doctype, ())}

	@property
	def her_rows(self) -> set[str]:
		"""Names of matched child rows (her CRM Contacts rows): Version entries naming them go"""
		return {
			name
			for doctype, names in self.matches.items()
			if frappe.get_meta(doctype).istable
			for name in names
		}

	def as_matched(self, include: tuple[str, ...] | None = None) -> dict[str, dict[str, str]]:
		"""The non-excluded matches in the shape `discovery_queries.find` reads"""
		return {
			doctype: dict.fromkeys(names, "linked")
			for doctype, names in self.matches.items()
			if include is None or doctype in include
		}


def build_context(request) -> Context:
	"""From the request's stored matches; ValueError when a stored identifier no longer normalizes"""
	matches, excluded, actions = defaultdict(set), set(), {}
	for row in request.get("matches") or []:
		key = (row.get("ref_doctype"), str(row.get("ref_name")))
		if row.get("excluded"):
			excluded.add(key)
			continue
		matches[key[0]].add(key[1])
		actions[key] = row.get("action")
	return Context(
		request_name=request.name,
		ids=Identifiers.from_rows(request.get("identifiers") or []),
		matches={doctype: frozenset(names) for doctype, names in matches.items()},
		excluded=frozenset(excluded),
		actions=actions,
	)
