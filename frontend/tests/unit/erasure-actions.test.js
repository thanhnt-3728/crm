import {
  JOB_TIMEOUT_SECONDS,
  availableActions,
  canAcknowledge,
  executionStalled,
  shouldPoll,
} from '@/utils/erasure-actions'

const base = { isPrivacyOfficer: true, isRequester: false, lastError: '' }
const only = (flags) => ({
  approve: false,
  reject: false,
  close: false,
  retry: false,
  submit: false,
  ...flags,
})

describe('availableActions', () => {
  it('lets a Privacy Officer who is not the requester approve and reject a pending request', () => {
    expect(availableActions({ ...base, status: 'Pending Approval' })).toEqual(
      only({ approve: true, reject: true }),
    )
  })

  it.each(['Draft', 'On Hold'])(
    'allows reject but not approve in %s',
    (status) => {
      expect(availableActions({ ...base, status })).toEqual(
        only({ reject: true }),
      )
    },
  )

  it('hides approve and reject from the requester even when she is a Privacy Officer', () => {
    expect(
      availableActions({
        ...base,
        isRequester: true,
        status: 'Pending Approval',
      }),
    ).toEqual(only())
  })

  it('hides every action from non Privacy Officers', () => {
    for (const status of [
      'Draft',
      'Pending Approval',
      'On Hold',
      'Executed',
      'Approved',
    ]) {
      expect(
        availableActions({
          ...base,
          isPrivacyOfficer: false,
          status,
          lastError: 'x',
        }),
      ).toEqual(only())
    }
  })

  it('lets the requester Privacy Officer close an Executed request', () => {
    expect(
      availableActions({ ...base, isRequester: true, status: 'Executed' }),
    ).toEqual(only({ close: true }))
  })

  it('offers retry only when Approved and the job failed', () => {
    expect(
      availableActions({ ...base, status: 'Approved', lastError: 'boom' }),
    ).toEqual(only({ retry: true }))
    expect(availableActions({ ...base, status: 'Approved' })).toEqual(only())
    expect(
      availableActions({
        ...base,
        isRequester: true,
        status: 'Approved',
        lastError: 'boom',
      }),
    ).toEqual(only({ retry: true }))
  })

  it('offers nothing on closed or rejected requests', () => {
    for (const status of ['Closed', 'Rejected']) {
      expect(availableActions({ ...base, status })).toEqual(only())
    }
  })
})

describe('submit for approval', () => {
  it('is for the requester of a Draft only', () => {
    const draft = { ...base, isPrivacyOfficer: false, status: 'Draft' }
    expect(availableActions({ ...draft, isRequester: true })).toEqual(
      only({ submit: true }),
    )
    expect(availableActions({ ...draft, isRequester: false })).toEqual(only())
    expect(
      availableActions({
        ...draft,
        isRequester: true,
        status: 'Pending Approval',
      }),
    ).toEqual(only())
  })
})

describe('shouldPoll', () => {
  it('polls only while Approved with no error', () => {
    expect(shouldPoll('Approved', '')).toBe(true)
    expect(shouldPoll('Approved', null)).toBe(true)
    expect(shouldPoll('Approved', 'boom')).toBe(false)
    expect(shouldPoll('Executed', '')).toBe(false)
    expect(shouldPoll(undefined, '')).toBe(false)
  })
})

describe('canAcknowledge', () => {
  const open = {
    status: 'Pending Approval',
    acknowledgedOn: null,
    isPrivacyOfficer: false,
    isRequester: true,
  }

  it('is for the requester or a Privacy Officer while unacknowledged', () => {
    expect(canAcknowledge(open)).toBe(true)
    expect(
      canAcknowledge({ ...open, isRequester: false, isPrivacyOfficer: true }),
    ).toBe(true)
    expect(canAcknowledge({ ...open, isRequester: false })).toBe(false)
  })

  it('is false once acknowledged or finished', () => {
    expect(canAcknowledge({ ...open, acknowledgedOn: '2026-11-03' })).toBe(
      false,
    )
    for (const status of ['Executed', 'Closed', 'Rejected']) {
      expect(canAcknowledge({ ...open, status })).toBe(false)
    }
  })
})

describe('stalled execution', () => {
  const approvedAt = 1_000_000_000_000
  const at = (seconds) => approvedAt + seconds * 1000
  const stalled = (seconds, status = 'Approved') =>
    executionStalled({ status, approvedAt, now: at(seconds) })

  it('uses the 1500 second job timeout', () => {
    expect(JOB_TIMEOUT_SECONDS).toBe(1500)
  })

  it('is false up to and at the timeout, true just over it', () => {
    expect(stalled(0)).toBe(false)
    expect(stalled(JOB_TIMEOUT_SECONDS - 1)).toBe(false)
    expect(stalled(JOB_TIMEOUT_SECONDS)).toBe(false)
    expect(stalled(JOB_TIMEOUT_SECONDS + 1)).toBe(true)
  })

  it('is false when not Approved or when there is no approval time', () => {
    expect(stalled(JOB_TIMEOUT_SECONDS + 100, 'Executed')).toBe(false)
    expect(
      executionStalled({ status: 'Approved', approvedAt: null, now: at(9999) }),
    ).toBe(false)
  })

  it('shows Retry to a Privacy Officer when stalled, with or without last_error', () => {
    const approved = { ...base, status: 'Approved' }
    expect(availableActions({ ...approved, stalled: true })).toEqual(
      only({ retry: true }),
    )
    expect(
      availableActions({ ...approved, stalled: true, lastError: 'boom' }),
    ).toEqual(only({ retry: true }))
    expect(availableActions({ ...approved, stalled: false })).toEqual(only())
    expect(
      availableActions({
        ...approved,
        isPrivacyOfficer: false,
        stalled: true,
      }),
    ).toEqual(only())
  })

  it('stops polling once stalled', () => {
    expect(shouldPoll('Approved', '', false)).toBe(true)
    expect(shouldPoll('Approved', '', true)).toBe(false)
  })
})
