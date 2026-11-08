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

function sameValue(a, b) {
  return String(a ?? '') === String(b ?? '')
}

// The keys whose form value differs from the saved doc, with the form's value.
export function changedFields(form, doc, keys) {
  const changed = {}
  for (const key of keys) {
    if (!sameValue(form[key], doc[key])) changed[key] = form[key]
  }
  return changed
}

// The form after the saved doc was refreshed. A field the user has edited since
// the last sync (form differs from baseline) keeps their text; any other field
// takes the doc's value. So a table save never wipes unsaved typing, and a form
// save ends clean because the doc now holds what the form holds.
export function mergeForm(form, baseline, doc, keys) {
  const merged = {}
  for (const key of keys) {
    const edited = !sameValue(form[key], baseline[key])
    merged[key] = edited ? form[key] : (doc[key] ?? '')
  }
  return merged
}

export function confirmationMatches(typed, requestName) {
  return (typed || '').trim() === requestName
}
