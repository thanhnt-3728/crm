import {
  canApprove,
  confirmMatches,
  daysLeftLabel,
  notificationRoute,
  recordRoute,
  sortByDaysLeft,
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
