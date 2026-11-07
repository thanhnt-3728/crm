// Pure helpers for the erasure request screens.

export const RESPONSE_DAYS = 45

export const OUTCOMES = ['Completed', 'Partly completed', 'Denied']

export function daysLeftLabel(daysLeft) {
  if (daysLeft === null || daysLeft === undefined) return ''
  if (daysLeft >= 0) return `${daysLeft} of ${RESPONSE_DAYS} days left`
  const overdue = -daysLeft
  return `Overdue by ${overdue} ${overdue === 1 ? 'day' : 'days'}`
}

const STATUS_THEMES = {
  Logged: 'gray',
  'Awaiting Sign-off': 'blue',
  'On Hold': 'orange',
  Erased: 'green',
  Closed: 'green',
  Declined: 'red',
}

export function statusTheme(status) {
  return STATUS_THEMES[status] || 'gray'
}

const MATCH_ROUTES = {
  'CRM Lead': { name: 'Lead', param: 'leadId' },
  'CRM Deal': { name: 'Deal', param: 'dealId' },
  Contact: { name: 'Contact', param: 'contactId' },
}

export function matchRoute(doctype, name) {
  const target = MATCH_ROUTES[doctype]
  if (!target || !name) return null
  return { name: target.name, params: { [target.param]: name } }
}

export function confirmationMatches(typed, requestName) {
  return (typed || '').trim() === requestName
}
