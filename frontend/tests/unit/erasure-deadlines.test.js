import {
  deadlineState,
  requestHighlights,
  todayString,
} from '@/utils/erasure-deadlines'

describe('todayString', () => {
  it('formats the local calendar date with zero padding', () => {
    expect(todayString(new Date(2026, 0, 9, 23, 59))).toBe('2026-01-09')
    expect(todayString(new Date(2026, 10, 5, 0, 0))).toBe('2026-11-05')
  })
})

const TODAY = '2026-11-05'

describe('deadlineState', () => {
  it.each([
    ['2026-11-04', 'overdue'],
    ['2026-10-01', 'overdue'],
    ['2026-11-05', 'due-soon'],
    ['2026-11-06', 'due-soon'],
    ['2026-11-08', 'due-soon'],
    ['2026-11-09', 'ok'],
    ['2026-12-31', 'ok'],
  ])('due %s is %s', (due, expected) => {
    expect(deadlineState(due, TODAY)).toBe(expected)
  })

  it('ignores a time part on the due date', () => {
    expect(deadlineState('2026-11-04 23:59:59', TODAY)).toBe('overdue')
    expect(deadlineState('2026-11-05 00:00:00', TODAY)).toBe('due-soon')
  })

  it('counts calendar days across a month and a year end', () => {
    expect(deadlineState('2027-01-02', '2026-12-30')).toBe('due-soon')
    expect(deadlineState('2027-01-03', '2026-12-30')).toBe('ok')
    expect(deadlineState('2026-03-01', '2026-02-27')).toBe('due-soon')
  })

  it('is done when the done flag is set, even past due', () => {
    expect(deadlineState('2026-01-01', TODAY, true)).toBe('done')
  })

  it('treats a missing due date as ok, not overdue', () => {
    expect(deadlineState(null, TODAY)).toBe('ok')
    expect(deadlineState('', TODAY)).toBe('ok')
  })
})

describe('requestHighlights', () => {
  const base = {
    status: 'Pending Approval',
    ack_due: '2026-11-04',
    response_due: '2026-11-05',
    acknowledged_on: null,
  }

  it('highlights both open deadlines', () => {
    expect(requestHighlights(base, TODAY)).toEqual({
      ack: 'overdue',
      response: 'due-soon',
    })
  })

  it('drops the ack highlight once acknowledged, keeps the response one', () => {
    const result = requestHighlights(
      { ...base, acknowledged_on: '2026-11-03' },
      TODAY,
    )
    expect(result).toEqual({ ack: 'done', response: 'due-soon' })
  })

  it.each(['Executed', 'Closed', 'Rejected'])(
    '%s drops all highlights',
    (s) => {
      expect(requestHighlights({ ...base, status: s }, TODAY)).toEqual({
        ack: 'done',
        response: 'done',
      })
    },
  )

  it.each(['Draft', 'Pending Approval', 'On Hold', 'Approved'])(
    '%s keeps highlights',
    (s) => {
      expect(requestHighlights({ ...base, status: s }, TODAY).ack).toBe(
        'overdue',
      )
    },
  )
})
