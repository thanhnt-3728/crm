import {
  closeFormError,
  closeOutcomeOptions,
  complianceNotificationRoute,
  isComplianceView,
  recordRoute,
} from '@/utils/erasureRequestDisplay'

describe('complianceNotificationRoute', () => {
  it('ignores other notification types', () => {
    expect(
      complianceNotificationRoute({ type: 'Mention', route_name: 'Lead' }),
    ).toBeNull()
  })

  it('opens the deal for a deal owner told to remove the person', () => {
    expect(
      complianceNotificationRoute({
        type: 'Compliance',
        route_name: 'Deal',
        reference_name: 'CRM-DEAL-1',
        notification_type_doctype: 'CRM Erasure Request',
        notification_type_doc: 'PDR-0001',
      }),
    ).toEqual({ name: 'Deal', params: { dealId: 'CRM-DEAL-1' } })
  })

  it('opens the request from its notification doc', () => {
    expect(
      complianceNotificationRoute({
        type: 'Compliance',
        route_name: 'Lead',
        reference_name: 'PDR-0002',
        notification_type_doctype: 'CRM Erasure Request',
        notification_type_doc: 'PDR-0002',
      }),
    ).toEqual({ name: 'ErasureRequest', params: { requestId: 'PDR-0002' } })
  })

  it('opens the request when only the reference names it', () => {
    expect(
      complianceNotificationRoute({
        type: 'Compliance',
        route_name: 'Lead',
        reference_name: 'PDR-0003',
      }),
    ).toEqual({ name: 'ErasureRequest', params: { requestId: 'PDR-0003' } })
  })

  it('opens the list with the mail for an inbound email notice', () => {
    expect(
      complianceNotificationRoute({
        type: 'Compliance',
        route_name: 'Lead',
        reference_name: 'abc123',
      }),
    ).toEqual({ name: 'ErasureRequests', query: { mail: 'abc123' } })
  })

  it('opens the list when the notice names nothing', () => {
    expect(
      complianceNotificationRoute({ type: 'Compliance', route_name: 'Lead' }),
    ).toEqual({ name: 'ErasureRequests' })
  })
})

describe('recordRoute', () => {
  it('links leads, deals and contacts', () => {
    expect(recordRoute('CRM Lead', 'L-1')).toEqual({
      name: 'Lead',
      params: { leadId: 'L-1' },
    })
    expect(recordRoute('CRM Deal', 'D-1')).toEqual({
      name: 'Deal',
      params: { dealId: 'D-1' },
    })
    expect(recordRoute('Contact', 'Marisol Vega')).toEqual({
      name: 'Contact',
      params: { contactId: 'Marisol Vega' },
    })
  })

  it('has no link for other record types', () => {
    expect(recordRoute('Communication', 'abc')).toBeNull()
  })
})

describe('closeOutcomeOptions', () => {
  it('lets an erased request close as completed or partly completed', () => {
    expect(closeOutcomeOptions('Erased')).toEqual([
      'Completed',
      'Partly completed',
    ])
  })

  it('closes a declined request as denied only', () => {
    expect(closeOutcomeOptions('Declined')).toEqual(['Denied'])
  })
})

describe('closeFormError', () => {
  const erased = { status: 'Erased', checklist: [], denial_reason: '' }
  const form = { date: '2026-12-01', outcome: 'Completed', reason: '' }

  it('is empty when everything needed is given', () => {
    expect(closeFormError(form, erased)).toBe('')
  })

  it('blocks while a checklist item is open and says how many', () => {
    const request = {
      ...erased,
      checklist: [{ done: 1 }, { done: 0 }, { done: 0 }],
    }
    expect(closeFormError(form, request)).toBe(
      '2 checklist items are still open',
    )
    expect(closeFormError(form, { ...erased, checklist: [{ done: 0 }] })).toBe(
      '1 checklist item is still open',
    )
  })

  it('needs the date answered and an outcome', () => {
    expect(closeFormError({ ...form, date: '' }, erased)).toBe(
      'Enter the date the requester was answered',
    )
    expect(closeFormError({ ...form, outcome: '' }, erased)).toBe(
      'Choose an outcome',
    )
  })

  it('needs a reason for partly completed and denied', () => {
    expect(
      closeFormError({ ...form, outcome: 'Partly completed' }, erased),
    ).toBe('A reason is required for this outcome')
    expect(
      closeFormError(
        { ...form, outcome: 'Partly completed', reason: 'Contract exception' },
        erased,
      ),
    ).toBe('')
  })

  it('accepts the decline reason already on the request for a denial', () => {
    const declined = {
      status: 'Declined',
      checklist: [],
      denial_reason: 'Identity not verifiable',
    }
    expect(closeFormError({ ...form, outcome: 'Denied' }, declined)).toBe('')
  })
})

describe('isComplianceView', () => {
  it('is true when any Compliance-only action is available', () => {
    expect(isComplianceView({ approve: true })).toBe(true)
    expect(isComplianceView({ manage_checklist: true })).toBe(true)
    expect(isComplianceView({ close: true, edit: false })).toBe(true)
  })

  it('is false for the shared flags alone and for no flags', () => {
    expect(isComplianceView({ edit: true, submit: true })).toBe(false)
    expect(isComplianceView({})).toBe(false)
    expect(isComplianceView(undefined)).toBe(false)
  })
})
