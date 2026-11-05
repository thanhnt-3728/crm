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

// Unconfirmed matches on the approval screen, labelled by record type.
export function unconfirmedMatchItems(matches) {
  const labels = { 'CRM Lead': 'Lead', 'CRM Deal': 'Deal', Contact: 'Contact' }
  return (matches || []).map((match) => ({
    ...match,
    kind: __(labels[match.doctype] || match.doctype),
    route: recordRoute(match.doctype, match.name),
  }))
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

// -- Logging a request ---------------------------------------------------------------

export const CHANNELS = ['Email', 'Phone', 'Web form', 'Mail', 'Other']
export const IDENTIFIER_KINDS = ['Email', 'Phone']

// What the requester is picked from when logging from a deal: the deal's
// contacts, labelled so two people with the same name can be told apart.
export function contactChoices(contacts) {
  return (contacts || [])
    .filter((row) => row.contact)
    .map((row) => ({
      value: row.contact,
      label: [row.full_name || row.contact, row.email || row.mobile_no]
        .filter(Boolean)
        .join(' - '),
    }))
}

// The record a request starts from. A request can only start from a lead or a
// contact, so a deal starts from the contact picked as the requester.
export function startRecord(doctype, name, contact) {
  if (doctype === 'CRM Deal') {
    return contact
      ? { startDoctype: 'Contact', startName: contact }
      : { startDoctype: '', startName: '' }
  }
  return { startDoctype: doctype || '', startName: name || '' }
}

function identifierKey(row) {
  const value = String(row.value || '').trim()
  return row.kind === 'Phone'
    ? `Phone:${value.replace(/\D/g, '')}`
    : `Email:${value.toLowerCase()}`
}

// De-duplicated, trimmed, non-empty rows; the server does its own normalising.
export function cleanIdentifiers(rows) {
  const seen = new Set()
  const result = []
  for (const row of rows || []) {
    const value = String(row.value || '').trim()
    if (!value || !IDENTIFIER_KINDS.includes(row.kind)) continue
    const key = identifierKey({ kind: row.kind, value })
    if (seen.has(key)) continue
    seen.add(key)
    result.push({ kind: row.kind, value })
  }
  return result
}

// The emails and phones held on a lead or contact, for showing before submit.
// The server prefills them itself; this is display only.
export function recordIdentifiers(doctype, doc) {
  if (!doc) return []
  const rows = []
  if (doctype === 'CRM Lead') {
    rows.push(
      { kind: 'Email', value: doc.email },
      { kind: 'Phone', value: doc.mobile_no },
      { kind: 'Phone', value: doc.phone },
    )
  } else {
    for (const row of doc.email_ids || [])
      rows.push({ kind: 'Email', value: row.email_id })
    for (const row of doc.phone_nos || [])
      rows.push({ kind: 'Phone', value: row.phone })
    rows.push(
      { kind: 'Email', value: doc.email_id },
      { kind: 'Phone', value: doc.mobile_no },
      { kind: 'Phone', value: doc.phone },
    )
  }
  return cleanIdentifiers(rows)
}

export function recordPersonName(doctype, doc) {
  if (!doc) return ''
  if (doctype === 'CRM Lead') {
    return (
      doc.lead_name || [doc.first_name, doc.last_name].filter(Boolean).join(' ')
    ).trim()
  }
  return (doc.full_name || doc.first_name || '').trim()
}

export function canLogRequest(form) {
  return Boolean(form.channel && form.receivedOn && form.startReady !== false)
}

// The arguments of `crm.api.erasure.create_request`.
export function buildCreateRequest(form) {
  const payload = {
    channel: form.channel,
    received_on: form.receivedOn,
    requester_names: (form.requesterNames || '').trim(),
    original_message: (form.originalMessage || '').trim(),
    identifiers: cleanIdentifiers(form.identifiers),
  }
  if (form.startDoctype && form.startName) {
    payload.start_doctype = form.startDoctype
    payload.start_name = form.startName
  }
  return payload
}

// -- Privacy settings ----------------------------------------------------------------

export const PERSONAL_FIELD_DOCTYPES = [
  'CRM Lead',
  'CRM Deal',
  'Contact',
  'CRM Contacts',
  'Address',
]

// Rows with both parts filled, each field once per document type.
export function cleanPersonalFields(rows) {
  const seen = new Set()
  const result = []
  for (const row of rows || []) {
    const fieldname = String(row.fieldname || '').trim()
    if (!row.document_type || !fieldname) continue
    const key = `${row.document_type}:${fieldname}`
    if (seen.has(key)) continue
    seen.add(key)
    result.push({ document_type: row.document_type, fieldname })
  }
  return result
}

// The choices for one row's field select: the document type's fields, minus
// those another row of the same type already lists, plus the row's own value
// (a hidden or removed field must still show what is saved).
export function personalFieldChoices(fields, rows, row) {
  const taken = new Set(
    (rows || [])
      .filter(
        (other) => other !== row && other.document_type === row.document_type,
      )
      .map((other) => other.fieldname),
  )
  const choices = (fields || [])
    .filter((field) => !taken.has(field.fieldname))
    .map((field) => ({
      value: field.fieldname,
      label: field.label
        ? `${field.label} (${field.fieldname})`
        : field.fieldname,
    }))
  if (row.fieldname && !choices.some((c) => c.value === row.fieldname)) {
    choices.unshift({ value: row.fieldname, label: row.fieldname })
  }
  return choices
}

// The arguments of `crm.api.erasure.save_privacy_settings`.
export function buildSettingsPayload(form) {
  return {
    head_of_compliance: form.headOfCompliance || '',
    contract_retention_months: Math.max(
      0,
      parseInt(form.contractRetentionMonths, 10) || 0,
    ),
    personal_fields: cleanPersonalFields(form.personalFields),
  }
}
