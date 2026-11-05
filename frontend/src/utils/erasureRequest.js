// Display helpers for erasure requests (UI hints only; the server is authoritative).

const RESPONSE_WINDOW_DAYS = 45

const statusThemes = {
  Logged: 'gray',
  'Awaiting Sign-off': 'blue',
  'On Hold': 'orange',
  Erasing: 'blue',
  Erased: 'green',
  Declined: 'red',
  Closed: 'gray',
}

export function daysLeftLabel(daysLeft) {
  if (daysLeft === 0) return __('Due today')
  if (daysLeft < 0) {
    const overdue = -daysLeft
    return overdue === 1
      ? __('1 day overdue')
      : __('{0} days overdue', [overdue])
  }
  return __('{0} of {1} days left', [daysLeft, RESPONSE_WINDOW_DAYS])
}

export function urgencyTheme(daysLeft) {
  if (daysLeft <= 5) return 'red'
  if (daysLeft <= 15) return 'orange'
  return 'gray'
}

export function statusTheme(status) {
  return statusThemes[status] ?? 'gray'
}

export function canApprove(request, sessionUser, isCompliance) {
  return (
    Boolean(isCompliance) &&
    request.status === 'Awaiting Sign-off' &&
    request.logged_by !== sessionUser
  )
}

export function confirmMatches(typed, requestName) {
  return typed.trim() === requestName
}

// Where a notification opens, or null when it points at nothing (the server
// sends no route_name then, and the panel must not navigate).
export function notificationRoute(notification) {
  const { route_name: name, reference_name: ref, hash } = notification
  if (!name || !ref) return null
  const param =
    { Deal: 'dealId', ErasureRequest: 'requestId' }[name] ?? 'leadId'
  return { name, params: { [param]: ref }, hash }
}

// Open requests soonest-due first; closed ones (no clock any more) go last.
export function sortByDaysLeft(requests) {
  const open = (request) => request.status !== 'Closed'
  return [...requests].sort(
    (a, b) =>
      Number(open(b)) - Number(open(a)) ||
      (open(a) ? a.days_left - b.days_left : 0) ||
      a.name.localeCompare(b.name),
  )
}

const recordRoutes = {
  'CRM Lead': ['Lead', 'leadId'],
  'CRM Deal': ['Deal', 'dealId'],
  Contact: ['Contact', 'contactId'],
}

// The page of a matched record, or null for a doctype that has none.
export function recordRoute(doctype, name) {
  const target = recordRoutes[doctype]
  if (!target || !name) return null
  return { name: target[0], params: { [target[1]]: name } }
}

// The first message of a failed server call (a rule the server enforces).
export function errorText(error) {
  return error?.messages?.[0] || error?.message || __('Something went wrong')
}
