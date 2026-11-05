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
