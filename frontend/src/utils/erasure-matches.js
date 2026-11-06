// Pure helpers for the erasure UI: grouping, exclusion state, typed confirmation
// and prefill of the person's identifiers from a Lead, Deal or Contact doc.

export function matchKey(row) {
  return `${row.ref_doctype}::${row.ref_name}`
}

// Groups flat match rows by doctype, in first-seen order.
export function groupMatches(rows) {
  const groups = new Map()
  for (const row of rows || []) {
    if (!groups.has(row.ref_doctype)) {
      groups.set(row.ref_doctype, {
        doctype: row.ref_doctype,
        count: 0,
        excluded: 0,
        rows: [],
      })
    }
    const group = groups.get(row.ref_doctype)
    group.count += 1
    group.excluded += row.excluded ? 1 : 0
    group.rows.push({ ...row, key: matchKey(row) })
  }
  return [...groups.values()]
}

export function toggleExclusion(excluded, key) {
  const next = new Set(excluded)
  if (next.has(key)) next.delete(key)
  else next.add(key)
  return next
}

// Exact match of the request number; only leading/trailing whitespace is forgiven.
export function isConfirmationValid(typed, name) {
  if (typeof typed !== 'string' || typeof name !== 'string' || !name)
    return false
  return typed.trim() === name
}

// First server message of a frappe-ui call error, else the fallback.
export function serverMessage(error, fallback) {
  return error?.messages?.[0] || error?.message || fallback
}

// The approve endpoint raises ErasurePreviewStale when matches changed since the preview.
export function isStalePreviewError(error) {
  return error?.exc_type === 'ErasurePreviewStale'
}

function clean(value) {
  return typeof value === 'string' ? value.trim() : ''
}

function addUnique(list, value, keyOf = (v) => v) {
  const text = clean(value)
  if (text && !list.some((item) => keyOf(item) === keyOf(text))) list.push(text)
}

export function prefillIdentifiers(doc, doctype) {
  const out = { subject_name: '', emails: [], phones: [] }
  if (!doc) return out

  const first = [doc.first_name, doc.last_name]
    .map(clean)
    .filter(Boolean)
    .join(' ')
  out.subject_name = clean(doc.lead_name) || clean(doc.full_name) || first || ''

  const lower = (v) => v.toLowerCase()
  const addEmail = (v) => addUnique(out.emails, v, lower)
  const addPhone = (v) => addUnique(out.phones, v)

  for (const value of [doc.email, doc.email_id]) addEmail(value)
  for (const value of [doc.mobile_no, doc.phone]) addPhone(value)
  for (const row of doc.email_ids || []) addEmail(row.email_id)
  for (const row of doc.phone_nos || []) addPhone(row.phone)
  if (doctype === 'CRM Deal') {
    for (const row of doc.contacts || []) {
      addEmail(row.email)
      addPhone(row.mobile_no)
      addPhone(row.phone)
    }
  }
  return out
}

// Outcome JSON ({doctype: count, ...} possibly nested) as [label, value] lines;
// invalid or empty JSON gives no lines.
export function outcomeEntries(outcome) {
  let data = outcome
  if (typeof outcome === 'string') {
    try {
      data = JSON.parse(outcome)
    } catch {
      return []
    }
  }
  const lines = []
  const walk = (value, path) => {
    if (value && typeof value === 'object') {
      for (const [key, inner] of Object.entries(value)) {
        walk(inner, path ? `${path} / ${key}` : key)
      }
    } else if (path) {
      lines.push([path, value])
    }
  }
  walk(data, '')
  return lines
}

// New rows first inside each group (stable); returns new group objects.
export function sortNewFirst(groups) {
  const rank = (row) => (row.new_since_logging ? 0 : 1)
  return (groups || []).map((group) => ({
    ...group,
    rows: [...group.rows].sort((a, b) => rank(a) - rank(b)),
  }))
}

export function countNewRows(groups) {
  let count = 0
  for (const group of groups || []) {
    count += group.rows.filter((row) => row.new_since_logging).length
  }
  return count
}

// Approve needs the typed number, and a ticked review box while new rows exist.
export function canConfirmApproval({ typed, name, newCount, reviewed }) {
  return isConfirmationValid(typed, name) && (!newCount || Boolean(reviewed))
}

export function sameKeys(a, b) {
  return a.size === b.size && [...a].every((key) => b.has(key))
}

// A row excluded only because its parent is cannot be toggled; the server ignores its key.
export function isToggleable(row) {
  return row.reason !== 'via_excluded'
}

// Keys the user excluded herself (preview rows carry `excluded` and `key`).
export function excludedKeys(groups) {
  const keys = new Set()
  for (const group of groups || []) {
    for (const row of group.rows) {
      if (row.excluded && isToggleable(row)) keys.add(row.key)
    }
  }
  return keys
}
