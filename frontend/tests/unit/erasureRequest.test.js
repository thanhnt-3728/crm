import { describe, expect, it } from 'vitest'
import {
  confirmationMatches,
  daysLeftLabel,
  matchRoute,
  statusTheme,
} from '@/utils/erasureRequest'

describe('daysLeftLabel', () => {
  it('counts down', () => expect(daysLeftLabel(14)).toBe('14 of 45 days left'))
  it('shows zero', () => expect(daysLeftLabel(0)).toBe('0 of 45 days left'))
  it('shows overdue', () => {
    expect(daysLeftLabel(-1)).toBe('Overdue by 1 day')
    expect(daysLeftLabel(-3)).toBe('Overdue by 3 days')
  })
  it('is empty for closed', () => expect(daysLeftLabel(null)).toBe(''))
})

describe('statusTheme', () => {
  it('maps statuses', () => {
    expect(statusTheme('On Hold')).toBe('orange')
    expect(statusTheme('Declined')).toBe('red')
    expect(statusTheme('Logged')).toBe('gray')
    expect(statusTheme('Awaiting Sign-off')).toBe('blue')
    expect(statusTheme('Erased')).toBe('green')
    expect(statusTheme('Closed')).toBe('green')
  })
})

describe('matchRoute', () => {
  it('links each record type to its page', () => {
    expect(matchRoute('CRM Lead', 'CRM-LEAD-1')).toEqual({
      name: 'Lead',
      params: { leadId: 'CRM-LEAD-1' },
    })
    expect(matchRoute('CRM Deal', 'CRM-DEAL-1')).toEqual({
      name: 'Deal',
      params: { dealId: 'CRM-DEAL-1' },
    })
    expect(matchRoute('Contact', 'Jo-Bloggs')).toEqual({
      name: 'Contact',
      params: { contactId: 'Jo-Bloggs' },
    })
  })
  it('has no link for other types', () => {
    expect(matchRoute('Note', 'x')).toBeNull()
  })
})

describe('confirmationMatches', () => {
  it('requires the exact request number', () => {
    expect(confirmationMatches(' PDR-0001 ', 'PDR-0001')).toBe(true)
    expect(confirmationMatches('pdr-0001', 'PDR-0001')).toBe(false)
    expect(confirmationMatches('PDR-001', 'PDR-0001')).toBe(false)
  })
})
