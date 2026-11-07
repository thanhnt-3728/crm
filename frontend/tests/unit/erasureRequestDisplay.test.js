import {
  confirmationMatches,
  createFailureGate,
  daysLeftLabel,
  daysLeftTone,
  errorText,
  jobBanner,
  splitIdentifiers,
  statusTheme,
} from '@/utils/erasureRequestDisplay'

describe('daysLeftLabel', () => {
  it('shows days left out of 45', () => {
    expect(daysLeftLabel(12)).toBe('12 of 45 days left')
    expect(daysLeftLabel(45)).toBe('45 of 45 days left')
  })

  it('shows 0 of 45 on the due day', () => {
    expect(daysLeftLabel(0)).toBe('0 of 45 days left')
  })

  it('says overdue for a negative number', () => {
    expect(daysLeftLabel(-3)).toBe('3 days overdue')
    expect(daysLeftLabel(-1)).toBe('1 day overdue')
  })

  it('is empty when the request has no deadline', () => {
    expect(daysLeftLabel(null)).toBe('')
    expect(daysLeftLabel(undefined)).toBe('')
  })
})

describe('daysLeftTone', () => {
  it('is red at 5 days or fewer and when overdue', () => {
    expect(daysLeftTone(5)).toBe('red')
    expect(daysLeftTone(0)).toBe('red')
    expect(daysLeftTone(-7)).toBe('red')
  })

  it('is gray above 5 days and when there is no deadline', () => {
    expect(daysLeftTone(6)).toBe('gray')
    expect(daysLeftTone(45)).toBe('gray')
    expect(daysLeftTone(null)).toBe('gray')
  })
})

describe('confirmationMatches', () => {
  it('needs the exact request number', () => {
    expect(confirmationMatches('PDR-0001', 'PDR-0001')).toBe(true)
  })

  it('does not trim or fold case', () => {
    expect(confirmationMatches(' PDR-0001', 'PDR-0001')).toBe(false)
    expect(confirmationMatches('PDR-0001 ', 'PDR-0001')).toBe(false)
    expect(confirmationMatches('pdr-0001', 'PDR-0001')).toBe(false)
  })

  it('never matches an empty number', () => {
    expect(confirmationMatches('', '')).toBe(false)
    expect(confirmationMatches(undefined, undefined)).toBe(false)
  })
})

describe('statusTheme', () => {
  it('gives each status a badge theme', () => {
    expect(statusTheme('On Hold')).toBe('orange')
    expect(statusTheme('Awaiting sign-off')).toBe('blue')
    expect(statusTheme('Erased')).toBe('green')
    expect(statusTheme('Declined')).toBe('red')
    expect(statusTheme('Logged')).toBe('gray')
    expect(statusTheme('Closed')).toBe('gray')
  })

  it('falls back to gray for an unknown status', () => {
    expect(statusTheme('Anything')).toBe('gray')
  })
})

describe('jobBanner', () => {
  it('is null when no job ran', () => {
    expect(jobBanner({ erasure_job_status: '' })).toBeNull()
    expect(jobBanner({})).toBeNull()
  })

  it('shows queued and running as progress', () => {
    expect(jobBanner({ erasure_job_status: 'Queued' })).toMatchObject({
      tone: 'blue',
      title: 'Erasure queued',
    })
    expect(jobBanner({ erasure_job_status: 'Running' })).toMatchObject({
      tone: 'blue',
      title: 'Erasure running',
    })
  })

  it('shows the stored error when the job failed', () => {
    const banner = jobBanner({
      erasure_job_status: 'Failed',
      erasure_error: 'Something broke',
    })
    expect(banner).toMatchObject({ tone: 'red', title: 'Erasure failed' })
    expect(banner.text).toContain('Something broke')
  })

  it('tells Compliance to review and approve again when the plan changed', () => {
    const banner = jobBanner({
      erasure_job_status: 'Failed',
      erasure_error: 'Plan changed since approval; review and approve again',
    })
    expect(banner.title).toBe('Plan changed since approval')
    expect(banner.text).toContain('review the preview')
    expect(banner.text).toContain('approve again')
  })
})

describe('errorText', () => {
  it('prefers the first server message and strips markup', () => {
    expect(
      errorText({ messages: ['<b>Not permitted</b>'], message: 'ignored' }),
    ).toBe('Not permitted')
  })

  it('falls back to the error message, then a generic text', () => {
    expect(errorText(new Error('Network down'))).toBe('Network down')
    expect(errorText(undefined)).toBe('Something went wrong')
  })
})

describe('splitIdentifiers', () => {
  it('splits on commas, semicolons and new lines and trims', () => {
    expect(splitIdentifiers('a@x.com, b@x.com;\n +1 530 555 0101 ')).toEqual([
      'a@x.com',
      'b@x.com',
      '+1 530 555 0101',
    ])
  })

  it('drops blanks and repeats', () => {
    expect(splitIdentifiers(' ,a@x.com,, a@x.com\n')).toEqual(['a@x.com'])
  })

  it('is empty for empty input', () => {
    expect(splitIdentifiers('')).toEqual([])
    expect(splitIdentifiers(null)).toEqual([])
  })
})

describe('createFailureGate', () => {
  it('lets only the first failure of a streak through', () => {
    const gate = createFailureGate()
    expect(gate.shouldNotify()).toBe(true)
    expect(gate.shouldNotify()).toBe(false)
    expect(gate.shouldNotify()).toBe(false)
  })

  it('notifies again after a success', () => {
    const gate = createFailureGate()
    gate.shouldNotify()
    gate.reset()
    expect(gate.shouldNotify()).toBe(true)
  })

  it('keeps separate gates apart', () => {
    const a = createFailureGate()
    const b = createFailureGate()
    a.shouldNotify()
    expect(b.shouldNotify()).toBe(true)
  })
})
