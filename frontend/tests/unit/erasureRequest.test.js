import { describe, expect, it } from 'vitest'
import {
  confirmationMatches,
  changedFields,
  daysLeftLabel,
  matchRoute,
  mergeForm,
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

describe('changedFields', () => {
  const keys = ['requester_name', 'original_message']

  it('is empty when the form matches the saved doc', () => {
    const doc = { requester_name: 'A', original_message: null }
    const form = { requester_name: 'A', original_message: '' }
    expect(changedFields(form, doc, keys)).toEqual({})
  })
  it('returns only the keys the user changed', () => {
    const doc = { requester_name: 'A', original_message: 'm' }
    const form = { requester_name: 'B', original_message: 'm' }
    expect(changedFields(form, doc, keys)).toEqual({ requester_name: 'B' })
  })
})

describe('mergeForm', () => {
  const keys = ['requester_name', 'original_message']

  it('keeps what the user typed when a table save refreshes the doc', () => {
    const baseline = { requester_name: '', original_message: '' }
    const form = { requester_name: 'Jo', original_message: '' }
    const doc = { requester_name: '', original_message: '' }
    expect(mergeForm(form, baseline, doc, keys)).toEqual({
      requester_name: 'Jo',
      original_message: '',
    })
  })
  it('takes server changes for fields the user has not touched', () => {
    const baseline = { requester_name: 'A', original_message: 'm' }
    const form = { requester_name: 'Jo', original_message: 'm' }
    const doc = { requester_name: 'A', original_message: 'new' }
    expect(mergeForm(form, baseline, doc, keys)).toEqual({
      requester_name: 'Jo',
      original_message: 'new',
    })
  })
  it('ends clean after the form itself was saved', () => {
    const baseline = { requester_name: '', original_message: '' }
    const form = { requester_name: 'Jo', original_message: '' }
    const saved = { requester_name: 'Jo', original_message: '' }
    const merged = mergeForm(form, baseline, saved, keys)
    expect(changedFields(merged, saved, keys)).toEqual({})
  })
  it('treats null and missing doc values as empty', () => {
    const form = { requester_name: '', original_message: '' }
    const merged = mergeForm(form, {}, { requester_name: null }, keys)
    expect(merged).toEqual({ requester_name: '', original_message: '' })
  })
})

describe('confirmationMatches', () => {
  it('requires the exact request number', () => {
    expect(confirmationMatches(' PDR-0001 ', 'PDR-0001')).toBe(true)
    expect(confirmationMatches('pdr-0001', 'PDR-0001')).toBe(false)
    expect(confirmationMatches('PDR-001', 'PDR-0001')).toBe(false)
  })
})
