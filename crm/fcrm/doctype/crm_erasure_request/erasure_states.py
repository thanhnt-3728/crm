# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt
"""Pure state machine of a CRM Erasure Request: which move is legal and who may make it"""

from collections.abc import Iterable

PRIVACY_OFFICER_ROLE = "Privacy Officer"

DRAFT = "Draft"
PENDING_APPROVAL = "Pending Approval"
ON_HOLD = "On Hold"
APPROVED = "Approved"
EXECUTED = "Executed"
CLOSED = "Closed"
REJECTED = "Rejected"

# Requests whose subject may not be deleted and whose data is about to be erased
OPEN_STATES = (DRAFT, PENDING_APPROVAL, ON_HOLD, APPROVED)
# Requests the hold rule watches
HOLD_STATES = (PENDING_APPROVAL, ON_HOLD)
# Nothing changes on these, not even acknowledged_on
TERMINAL_STATES = (CLOSED, REJECTED)

# Actors
REQUESTER = "requester"  # the user who logged the request (requested_by)
DECIDER = "decider"  # a Privacy Officer who is neither requested_by nor owner
PRIVACY_OFFICER = "privacy_officer"  # any Privacy Officer
SYSTEM = "system"  # server code: the hold rule and the execution job

TRANSITIONS = {
	(DRAFT, PENDING_APPROVAL): REQUESTER,
	(DRAFT, ON_HOLD): REQUESTER,
	(PENDING_APPROVAL, ON_HOLD): SYSTEM,
	(ON_HOLD, PENDING_APPROVAL): SYSTEM,
	(PENDING_APPROVAL, APPROVED): DECIDER,
	(APPROVED, EXECUTED): SYSTEM,
	(EXECUTED, CLOSED): PRIVACY_OFFICER,
	(DRAFT, REJECTED): DECIDER,
	(PENDING_APPROVAL, REJECTED): DECIDER,
	(ON_HOLD, REJECTED): DECIDER,
}


def transition_actor(from_status: str | None, to_status: str) -> str | None:
	"""The actor allowed to move a request from `from_status` to `to_status`, None if illegal"""
	return TRANSITIONS.get((from_status, to_status))


def can_transition(from_status: str | None, to_status: str) -> bool:
	return transition_actor(from_status, to_status) is not None


def can_decide(user: str, roles: Iterable[str], requested_by: str | None, owner: str | None) -> bool:
	"""Two-person rule: a Privacy Officer approves or rejects, never on a request they logged"""
	if not user or user == "Guest":
		return False
	return PRIVACY_OFFICER_ROLE in set(roles) and user not in (requested_by, owner)
