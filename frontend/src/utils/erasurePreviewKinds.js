// Rows the privacy module wrote about the request itself: the On Hold notices
// to deal owners and their queued emails. Their docnames are random hashes and
// mean nothing to the approver, so the approval dialog shows the count only.
const COUNT_ONLY_KINDS = [
  'hold_notifications',
  'hold_notification_logs',
  'hold_emails',
]

export function showsRecordNames(kind) {
  return !COUNT_ONLY_KINDS.includes(kind)
}
