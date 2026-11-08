import { describe, expect, it } from 'vitest'
import { notificationRoute } from '@/utils/notifications'

const route = (route_name, reference_name) =>
  notificationRoute({ route_name, reference_name, hash: '#n1' })

describe('notificationRoute', () => {
  it('opens a deal', () =>
    expect(route('Deal', 'D-1')).toEqual({
      name: 'Deal',
      params: { dealId: 'D-1' },
      hash: '#n1',
    }))
  it('opens a lead', () =>
    expect(route('Lead', 'L-1')).toEqual({
      name: 'Lead',
      params: { leadId: 'L-1' },
      hash: '#n1',
    }))
  it('opens an erasure request', () =>
    expect(route('Erasure Request', 'PDR-0001')).toEqual({
      name: 'Erasure Request',
      params: { requestId: 'PDR-0001' },
      hash: '#n1',
    }))
  it('opens mail from an erased person', () =>
    expect(route('Erasure Email', 'abc123')).toEqual({
      name: 'Erasure Email',
      params: { emailId: 'abc123' },
      hash: '#n1',
    }))
  it('opens the request list without params', () =>
    expect(route('Erasure Requests', 'x')).toEqual({
      name: 'Erasure Requests',
      params: {},
      hash: '#n1',
    }))
})
