import {
  canApprove,
  confirmMatches,
  daysLeftLabel,
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
