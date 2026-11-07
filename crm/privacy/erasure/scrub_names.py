# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Step 9, last [RT-6]: Contact and Address docnames carry her name ("Marisol Vega", "Marisol Vega-Billing").

They are renamed to the placeholder so every Link and Dynamic Link follows. The rename runs after every other step,
so each earlier step worked with the old docnames the plan was built from. An address shared with someone else is
renamed only when its docname holds her value ([I3]).
"""

import re

from crm.privacy.erasure.plan import ErasurePlan
from crm.privacy.erasure.rename_support import rename_to_placeholder
from crm.privacy.erasure.scrub_context import ScrubContext


def holds_her_name(docname: str, plan: ErasurePlan) -> bool:
	"""Whether a docname contains her full name or one of her identifiers as whole words (any case): "Ana" is in
	"Ana-Billing" but not in "Banana St-Billing"."""
	names = [*plan.her_values.get("full_name", []), *plan.her_values.get("lead_name", [])]
	values = [*names, *plan.identifiers.emails, *plan.identifiers.phones]
	return any(
		re.search(rf"(?<!\w){re.escape(value.strip())}(?!\w)", docname, re.IGNORECASE)
		for value in values
		if len(value.strip()) >= 3
	)


def scrub(plan: ErasurePlan, ctx: ScrubContext) -> None:
	renamed = [("Contact", name) for name in plan.targets["contacts"]]
	renamed += [("Address", name) for name in plan.targets["addresses"]]
	renamed += [("Address", name) for name in plan.shared_addresses if holds_her_name(name, plan)]
	for doctype, name in renamed:
		ctx.renames[(doctype, name)] = rename_to_placeholder(doctype, name, ctx.person)
