import { displayDate } from '@/composables/erasure-display-date'

describe('displayDate', () => {
  beforeEach(() => {
    window.sysdefaults = { date_format: 'dd-mm-yyyy' }
  })

  it('formats a date string with the site date format, without shifting the day', () => {
    expect(displayDate('2026-11-05')).toBe('05-11-2026')
    expect(displayDate('2026-01-01 23:59:59')).toBe('01-01-2026')
  })

  it('returns an empty string for a missing date', () => {
    expect(displayDate('')).toBe('')
    expect(displayDate(null)).toBe('')
  })
})
