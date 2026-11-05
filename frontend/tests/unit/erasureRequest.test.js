import {
  buildCreateRequest,
  buildSettingsPayload,
  canApprove,
  canLogRequest,
  cleanIdentifiers,
  cleanPersonalFields,
  confirmMatches,
  contactChoices,
  daysLeftLabel,
  notificationRoute,
  personalFieldChoices,
  recordIdentifiers,
  recordPersonName,
  recordRoute,
  sortByDaysLeft,
  startRecord,
  statusTheme,
  urgencyTheme,
} from '@/utils/erasureRequest'

describe('daysLeftLabel', () => {
  it('counts down days left', () => {
    expect(daysLeftLabel(33)).toBe('33 of 45 days left')
  })

  it('reads zero as due today', () => {
    expect(daysLeftLabel(0)).toBe('Due today')
  })

  it('reads negative days as overdue', () => {
    expect(daysLeftLabel(-2)).toBe('2 days overdue')
  })

  it('uses the singular for one day overdue', () => {
    expect(daysLeftLabel(-1)).toBe('1 day overdue')
  })
})

describe('urgencyTheme', () => {
  it('is red at five days or fewer', () => {
    expect(urgencyTheme(5)).toBe('red')
    expect(urgencyTheme(-3)).toBe('red')
  })

  it('is orange at fifteen days or fewer', () => {
    expect(urgencyTheme(6)).toBe('orange')
    expect(urgencyTheme(15)).toBe('orange')
  })

  it('is gray above fifteen days', () => {
    expect(urgencyTheme(16)).toBe('gray')
  })
})

describe('statusTheme', () => {
  it('maps On Hold to orange', () => {
    expect(statusTheme('On Hold')).toBe('orange')
  })

  it('maps Erased to green', () => {
    expect(statusTheme('Erased')).toBe('green')
  })

  it('maps Declined to red', () => {
    expect(statusTheme('Declined')).toBe('red')
  })
})

describe('canApprove', () => {
  it('refuses the person who logged the request', () => {
    expect(
      canApprove(
        { logged_by: 'a@x', status: 'Awaiting Sign-off' },
        'a@x',
        true,
      ),
    ).toBe(false)
  })

  it('allows another Compliance user on a request awaiting sign-off', () => {
    expect(
      canApprove(
        { logged_by: 'a@x', status: 'Awaiting Sign-off' },
        'b@x',
        true,
      ),
    ).toBe(true)
  })

  it('refuses a user without Compliance', () => {
    expect(
      canApprove(
        { logged_by: 'a@x', status: 'Awaiting Sign-off' },
        'b@x',
        false,
      ),
    ).toBe(false)
  })

  it('refuses a request that is not awaiting sign-off', () => {
    expect(
      canApprove({ logged_by: 'a@x', status: 'On Hold' }, 'b@x', true),
    ).toBe(false)
  })
})

describe('confirmMatches', () => {
  it('ignores surrounding whitespace', () => {
    expect(confirmMatches(' PDR-0001 ', 'PDR-0001')).toBe(true)
  })

  it('is case sensitive', () => {
    expect(confirmMatches('pdr-0001', 'PDR-0001')).toBe(false)
  })

  it('refuses a different request name', () => {
    expect(confirmMatches('PDR-0002', 'PDR-0001')).toBe(false)
  })
})

describe('notificationRoute', () => {
  it('opens a privacy request by its number', () => {
    expect(
      notificationRoute({
        route_name: 'ErasureRequest',
        reference_name: 'PDR-0001',
        hash: '',
      }),
    ).toEqual({
      name: 'ErasureRequest',
      params: { requestId: 'PDR-0001' },
      hash: '',
    })
  })

  it('keeps deals and leads on their own params', () => {
    expect(
      notificationRoute({ route_name: 'Deal', reference_name: 'D-1' }).params,
    ).toEqual({ dealId: 'D-1' })
    expect(
      notificationRoute({ route_name: 'Lead', reference_name: 'L-1' }).params,
    ).toEqual({ leadId: 'L-1' })
  })

  it('has no route when the notification points at nothing', () => {
    expect(notificationRoute({ route_name: null, reference_name: null })).toBe(
      null,
    )
    expect(notificationRoute({ route_name: 'Lead', reference_name: '' })).toBe(
      null,
    )
  })
})

describe('sortByDaysLeft', () => {
  it('puts the soonest due first and closed requests last', () => {
    const rows = [
      { name: 'PDR-0003', status: 'Closed', days_left: -50 },
      { name: 'PDR-0002', status: 'Logged', days_left: 30 },
      { name: 'PDR-0001', status: 'Erased', days_left: -2 },
      { name: 'PDR-0004', status: 'Logged', days_left: 30 },
    ]
    expect(sortByDaysLeft(rows).map((r) => r.name)).toEqual([
      'PDR-0001',
      'PDR-0002',
      'PDR-0004',
      'PDR-0003',
    ])
  })

  it('does not change the list it is given', () => {
    const rows = [
      { name: 'B', status: 'Logged', days_left: 9 },
      { name: 'A', status: 'Logged', days_left: 1 },
    ]
    sortByDaysLeft(rows)
    expect(rows[0].name).toBe('B')
  })
})

describe('recordRoute', () => {
  it('maps matched doctypes to their pages', () => {
    expect(recordRoute('CRM Lead', 'L-1')).toEqual({
      name: 'Lead',
      params: { leadId: 'L-1' },
    })
    expect(recordRoute('CRM Deal', 'D-1').name).toBe('Deal')
    expect(recordRoute('Contact', 'C-1').params).toEqual({ contactId: 'C-1' })
  })

  it('returns null for other doctypes', () => {
    expect(recordRoute('Address', 'A-1')).toBe(null)
  })
})

describe('logging a request', () => {
  it('starts a lead request from the lead', () => {
    expect(startRecord('CRM Lead', 'CRM-LEAD-1')).toEqual({
      startDoctype: 'CRM Lead',
      startName: 'CRM-LEAD-1',
    })
  })

  it('starts a contact request from the contact', () => {
    expect(startRecord('Contact', 'Marisol Vega')).toEqual({
      startDoctype: 'Contact',
      startName: 'Marisol Vega',
    })
  })

  it('starts a deal request from the picked contact', () => {
    expect(startRecord('CRM Deal', 'CRM-DEAL-1', 'Marisol Vega')).toEqual({
      startDoctype: 'Contact',
      startName: 'Marisol Vega',
    })
  })

  it('has no start until a deal contact is picked', () => {
    expect(startRecord('CRM Deal', 'CRM-DEAL-1', '')).toEqual({
      startDoctype: '',
      startName: '',
    })
  })

  it('labels deal contacts and skips empty rows', () => {
    expect(
      contactChoices([
        { contact: 'c1', full_name: 'Marisol Vega', email: 'm@x.net' },
        { contact: 'c2', full_name: '' },
        { contact: '' },
      ]),
    ).toEqual([
      { value: 'c1', label: 'Marisol Vega - m@x.net' },
      { value: 'c2', label: 'c2' },
    ])
  })

  it('cleans identifiers: trims, drops empties and duplicates', () => {
    expect(
      cleanIdentifiers([
        { kind: 'Email', value: ' Marisol@X.net ' },
        { kind: 'Email', value: 'marisol@x.net' },
        { kind: 'Phone', value: '(916) 555-0100' },
        { kind: 'Phone', value: '916.555.0100' },
        { kind: 'Phone', value: '' },
        { kind: 'Fax', value: '123' },
      ]),
    ).toEqual([
      { kind: 'Email', value: 'Marisol@X.net' },
      { kind: 'Phone', value: '(916) 555-0100' },
    ])
  })

  it('lists a lead record identifiers', () => {
    expect(
      recordIdentifiers('CRM Lead', {
        email: 'm@x.net',
        mobile_no: '+19165550100',
        phone: '',
      }),
    ).toEqual([
      { kind: 'Email', value: 'm@x.net' },
      { kind: 'Phone', value: '+19165550100' },
    ])
  })

  it('lists a contact record identifiers across its child rows', () => {
    expect(
      recordIdentifiers('Contact', {
        email_ids: [{ email_id: 'm@x.net' }, { email_id: 'm2@x.net' }],
        phone_nos: [{ phone: '+19165550100' }],
        email_id: 'm@x.net',
        mobile_no: '+19165550100',
      }),
    ).toEqual([
      { kind: 'Email', value: 'm@x.net' },
      { kind: 'Email', value: 'm2@x.net' },
      { kind: 'Phone', value: '+19165550100' },
    ])
  })

  it('names the person on a lead or contact', () => {
    expect(recordPersonName('CRM Lead', { lead_name: 'Marisol Vega' })).toBe(
      'Marisol Vega',
    )
    expect(recordPersonName('Contact', { full_name: 'Marisol Vega' })).toBe(
      'Marisol Vega',
    )
    expect(recordPersonName('Contact', null)).toBe('')
  })

  it('needs a channel, a date and a picked requester', () => {
    const ok = { channel: 'Email', receivedOn: '2026-11-01' }
    expect(canLogRequest(ok)).toBe(true)
    expect(canLogRequest({ ...ok, channel: '' })).toBe(false)
    expect(canLogRequest({ ...ok, receivedOn: '' })).toBe(false)
    expect(canLogRequest({ ...ok, startReady: false })).toBe(false)
  })

  it('builds the create_request arguments', () => {
    expect(
      buildCreateRequest({
        channel: 'Email',
        receivedOn: '2026-11-01',
        requesterNames: ' Marisol Vega ',
        originalMessage: ' Please erase me ',
        identifiers: [
          { kind: 'Email', value: 'm@x.net' },
          { kind: 'Phone', value: '  ' },
        ],
        startDoctype: 'CRM Lead',
        startName: 'CRM-LEAD-1',
      }),
    ).toEqual({
      channel: 'Email',
      received_on: '2026-11-01',
      requester_names: 'Marisol Vega',
      original_message: 'Please erase me',
      identifiers: [{ kind: 'Email', value: 'm@x.net' }],
      start_doctype: 'CRM Lead',
      start_name: 'CRM-LEAD-1',
    })
  })

  it('leaves the start out of a blank form', () => {
    const payload = buildCreateRequest({
      channel: 'Mail',
      receivedOn: '2026-11-01',
    })
    expect(payload).not.toHaveProperty('start_doctype')
    expect(payload).not.toHaveProperty('start_name')
    expect(payload.identifiers).toEqual([])
  })
})

describe('privacy settings', () => {
  it('drops incomplete and repeated personal fields', () => {
    expect(
      cleanPersonalFields([
        { document_type: 'CRM Lead', fieldname: ' email ' },
        { document_type: 'CRM Lead', fieldname: 'email' },
        { document_type: 'Contact', fieldname: 'email' },
        { document_type: 'Contact', fieldname: '' },
        { document_type: '', fieldname: 'phone' },
      ]),
    ).toEqual([
      { document_type: 'CRM Lead', fieldname: 'email' },
      { document_type: 'Contact', fieldname: 'email' },
    ])
  })

  it('offers fields other rows of the type have not taken', () => {
    const rows = [
      { document_type: 'CRM Lead', fieldname: 'email' },
      { document_type: 'CRM Lead', fieldname: '' },
      { document_type: 'Contact', fieldname: 'phone' },
    ]
    const fields = [
      { fieldname: 'email', label: 'Email' },
      { fieldname: 'phone', label: 'Phone' },
    ]
    expect(personalFieldChoices(fields, rows, rows[1])).toEqual([
      { value: 'phone', label: 'Phone (phone)' },
    ])
    expect(personalFieldChoices(fields, rows, rows[0])).toEqual([
      { value: 'email', label: 'Email (email)' },
      { value: 'phone', label: 'Phone (phone)' },
    ])
  })

  it('keeps a saved field the meta no longer lists', () => {
    const row = { document_type: 'CRM Lead', fieldname: 'old_field' }
    expect(personalFieldChoices([], [row], row)).toEqual([
      { value: 'old_field', label: 'old_field' },
    ])
  })

  it('builds the save arguments and never carries a secret', () => {
    const payload = buildSettingsPayload({
      headOfCompliance: 'head@x.net',
      contractRetentionMonths: '36',
      personalFields: [{ document_type: 'Address', fieldname: 'city' }],
      hash_secret: 'nope',
    })
    expect(payload).toEqual({
      head_of_compliance: 'head@x.net',
      contract_retention_months: 36,
      personal_fields: [{ document_type: 'Address', fieldname: 'city' }],
    })
  })

  it('treats a bad or negative retention as zero', () => {
    expect(
      buildSettingsPayload({ contractRetentionMonths: '-3' })
        .contract_retention_months,
    ).toBe(0)
    expect(
      buildSettingsPayload({ contractRetentionMonths: 'x' })
        .contract_retention_months,
    ).toBe(0)
  })
})
