// Deadline highlighting for erasure requests. Dates are 'YYYY-MM-DD' strings
// (an optional time part is ignored) and `today` is injected, so no timezone
// conversion can shift a day.

const DUE_SOON_DAYS = 3
const FINISHED_STATUSES = ['Executed', 'Closed', 'Rejected']

function dayNumber(dateString) {
  const [year, month, day] = String(dateString)
    .slice(0, 10)
    .split('-')
    .map(Number)
  if (!year || !month || !day) return null
  return Date.UTC(year, month - 1, day) / 86400000
}

// Local calendar date as 'YYYY-MM-DD' (the user's own "today").
export function todayString(now = new Date()) {
  const pad = (n) => String(n).padStart(2, '0')
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`
}

export function deadlineState(dueDate, today, done = false) {
  if (done) return 'done'
  const due = dayNumber(dueDate || '')
  const now = dayNumber(today || '')
  if (due === null || now === null) return 'ok'
  if (due < now) return 'overdue'
  return due - now <= DUE_SOON_DAYS ? 'due-soon' : 'ok'
}

export function requestHighlights(request, today) {
  const finished = FINISHED_STATUSES.includes(request.status)
  return {
    ack: deadlineState(
      request.ack_due,
      today,
      finished || Boolean(request.acknowledged_on),
    ),
    response: deadlineState(request.response_due, today, finished),
  }
}

export const deadlineClasses = {
  overdue: 'text-ink-red-4 font-medium',
  'due-soon': 'text-ink-amber-3 font-medium',
  ok: 'text-ink-gray-7',
  done: 'text-ink-gray-5',
}
