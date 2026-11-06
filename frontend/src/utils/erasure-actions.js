// Which request actions to show. The server enforces every rule; this only
// hides what it would refuse.
// Header fields of the detail page. The child table of matches is left out on purpose.
export const REQUEST_DETAIL_FIELDS = [
  'name',
  'subject_name',
  'status',
  'requested_by',
  'received_on',
  'ack_due',
  'response_due',
  'acknowledged_on',
  'hold_reason',
  'rejection_reason',
  'last_error',
  'approved_on',
  'outcome',
  'known_limitations',
]

// The background job's timeout; an Approved request older than this has been lost.
export const JOB_TIMEOUT_SECONDS = 1500

// Approved for longer than the job can run (times in ms): the job died without leaving an error.
export function executionStalled({ status, approvedAt, now }) {
  return (
    status === 'Approved' &&
    Number.isFinite(approvedAt) &&
    now - approvedAt > JOB_TIMEOUT_SECONDS * 1000
  )
}

const REJECTABLE = ['Draft', 'Pending Approval', 'On Hold']

export function availableActions({
  status,
  isPrivacyOfficer,
  isRequester,
  lastError,
  stalled,
}) {
  const reviewer = isPrivacyOfficer && !isRequester
  return {
    approve: reviewer && status === 'Pending Approval',
    reject: reviewer && REJECTABLE.includes(status),
    close: isPrivacyOfficer && status === 'Executed',
    retry:
      isPrivacyOfficer &&
      status === 'Approved' &&
      Boolean(lastError || stalled),
    submit: isRequester && status === 'Draft',
  }
}

// An Approved request runs in a background job; poll until it ends or fails.
export function shouldPoll(status, lastError, stalled = false) {
  return status === 'Approved' && !lastError && !stalled
}

// Requester or Privacy Officer, until acknowledged or the request is finished.
export function canAcknowledge({
  status,
  acknowledgedOn,
  isPrivacyOfficer,
  isRequester,
}) {
  const finished = ['Executed', 'Closed', 'Rejected'].includes(status)
  return !acknowledgedOn && !finished && (isRequester || isPrivacyOfficer)
}
