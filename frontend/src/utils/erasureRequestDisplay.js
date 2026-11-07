// Display rules for CCPA erasure requests. Pure: no permissions are decided
// here, the server's `can` flags do that.

export const RESPONSE_DAYS = 45
export const URGENT_DAYS = 5
export const PLAN_CHANGED_ERROR = 'Plan changed since approval'

export function daysLeftLabel(daysLeft) {
  if (daysLeft === null || daysLeft === undefined) return ''
  if (daysLeft < 0) {
    const overdue = Math.abs(daysLeft)
    return overdue === 1
      ? __('{0} day overdue', [overdue])
      : __('{0} days overdue', [overdue])
  }
  return __('{0} of {1} days left', [daysLeft, RESPONSE_DAYS])
}

export function daysLeftTone(daysLeft) {
  if (daysLeft === null || daysLeft === undefined) return 'gray'
  return daysLeft <= URGENT_DAYS ? 'red' : 'gray'
}

// Exact on purpose: no trim, no case folding. The server compares again.
export function confirmationMatches(typed, requestNumber) {
  return Boolean(requestNumber) && typed === requestNumber
}

const STATUS_THEMES = {
  Logged: 'gray',
  'Awaiting sign-off': 'blue',
  'On Hold': 'orange',
  Erased: 'green',
  Declined: 'red',
  Closed: 'gray',
}

export function statusTheme(status) {
  return STATUS_THEMES[status] || 'gray'
}

// The banner for the erasure job: progress while Queued/Running, the stored
// error when Failed. A stale plan is a review step, not a fault.
export function jobBanner(request) {
  switch (request?.erasure_job_status) {
    case 'Queued':
      return {
        tone: 'blue',
        title: __('Erasure queued'),
        text: __('The request is locked until the erasure job finishes.'),
      }
    case 'Running':
      return {
        tone: 'blue',
        title: __('Erasure running'),
        text: __('The request is locked until the erasure job finishes.'),
      }
    case 'Failed': {
      const error = request.erasure_error || ''
      if (error.startsWith(PLAN_CHANGED_ERROR)) {
        return {
          tone: 'red',
          title: __('Plan changed since approval'),
          text: __(
            'Records changed after approval, so nothing was erased. Compliance should review the preview and approve again.',
          ),
        }
      }
      return {
        tone: 'red',
        title: __('Erasure failed'),
        text: __('Nothing was erased. {0}', [error]),
      }
    }
    default:
      return null
  }
}

// Where a Compliance notification leads. The notifications API reports every
// reference that is not a deal as a lead, so the request is read from the
// notification doc, then from a PDR reference; anything else is an inbound
// email (opened from the requests list).
export function complianceNotificationRoute(notification) {
  if (notification.type !== 'Compliance') return null
  if (notification.route_name === 'Deal') {
    return { name: 'Deal', params: { dealId: notification.reference_name } }
  }
  const request =
    notification.notification_type_doctype === 'CRM Erasure Request'
      ? notification.notification_type_doc
      : /^PDR-/.test(notification.reference_name || '')
        ? notification.reference_name
        : null
  if (request) return { name: 'ErasureRequest', params: { requestId: request } }
  if (notification.reference_name) {
    return {
      name: 'ErasureRequests',
      query: { mail: notification.reference_name },
    }
  }
  return { name: 'ErasureRequests' }
}

// What a failed call says: the first server message without markup.
export function errorText(error) {
  const raw = error?.messages?.[0] || error?.message || ''
  return (
    String(raw)
      .replace(/<[^>]*>/g, '')
      .trim() || __('Something went wrong')
  )
}

// "a@x.com, b@x.com" or one per line, to a list without blanks or repeats.
export function splitIdentifiers(text) {
  const values = String(text || '')
    .split(/[\n,;]+/)
    .map((value) => value.trim())
    .filter(Boolean)
  return [...new Set(values)]
}

const RECORD_ROUTES = {
  'CRM Lead': ['Lead', 'leadId'],
  'CRM Deal': ['Deal', 'dealId'],
  Contact: ['Contact', 'contactId'],
}

export function recordRoute(doctype, name) {
  const target = RECORD_ROUTES[doctype]
  return target ? { name: target[0], params: { [target[1]]: name } } : null
}

// An erased request closes as completed or partly completed; a declined one as denied.
export function closeOutcomeOptions(status) {
  return status === 'Declined' ? ['Denied'] : ['Completed', 'Partly completed']
}

const REASON_OUTCOMES = ['Partly completed', 'Denied']

// Why the close form cannot be submitted yet, or '' when it can. The server
// checks every rule again.
export function closeFormError(form, request) {
  const open = (request.checklist || []).filter((item) => !item.done).length
  if (open) {
    return open === 1
      ? __('1 checklist item is still open')
      : __('{0} checklist items are still open', [open])
  }
  if (!form.date) return __('Enter the date the requester was answered')
  if (!form.outcome) return __('Choose an outcome')
  const hasReason = (form.reason || '').trim() || request.denial_reason
  if (REASON_OUTCOMES.includes(form.outcome) && !hasReason) {
    return __('A reason is required for this outcome')
  }
  return ''
}

const COMPLIANCE_ACTIONS = [
  'approve',
  'decline',
  'close',
  'manage_checklist',
  'mark_acknowledged',
  'recheck_hold',
]

// `edit` and `submit` are shared with the logger, so only these flags say the
// viewer is Compliance. Used to show Compliance-only sections, never to grant
// anything: the server checks every call.
export function isComplianceView(can) {
  return COMPLIANCE_ACTIONS.some((action) => can?.[action])
}

// One notice per streak of failed refreshes, not one every 3 seconds: the
// first failure notifies, the next ones stay quiet until a refresh succeeds.
export function createFailureGate() {
  let failing = false
  return {
    shouldNotify() {
      const first = !failing
      failing = true
      return first
    },
    reset() {
      failing = false
    },
  }
}
