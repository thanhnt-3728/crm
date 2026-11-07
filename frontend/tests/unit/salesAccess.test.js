import { describe, it, expect, vi, beforeEach } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { canReadSalesData, runIfSalesUser } from '@/utils/salesAccess'

let role = null
let usersLoaded // settles the users resource's promise
let docResources = []
let listResources = []

vi.mock('frappe-ui', () => ({
  createDocumentResource(options) {
    const resource = { options, reload: vi.fn(), get: { fetch: vi.fn() } }
    docResources.push(resource)
    return resource
  },
  createListResource(options) {
    const resource = { options, reload: vi.fn(), fetch: vi.fn(), data: [] }
    listResources.push(resource)
    return resource
  },
  createResource: () => ({ submit: vi.fn(), reload: vi.fn() }),
  toast: {},
}))

vi.mock('@/stores/users', () => ({
  usersStore: () => ({
    users: {
      reload: vi.fn(),
      promise: new Promise((resolve) => (usersLoaded = resolve)),
    },
    getUser: () => ({}),
    getUserRole: () => role,
  }),
}))

vi.mock('@/stores/session', () => ({ sessionStore: () => ({ user: 'a@b.c' }) }))

const socket = { on: vi.fn(), io: { on: vi.fn() } }
vi.mock('@/stores/global', () => ({ globalStore: () => ({ $socket: socket }) }))

describe('canReadSalesData', () => {
  it('is false only for a user whose top role is Compliance', () => {
    expect(canReadSalesData('Compliance')).toBe(false)
    for (const known of ['System Manager', 'Sales Manager', 'Sales User']) {
      expect(canReadSalesData(known)).toBe(true)
    }
  })

  it('keeps the old behaviour while the role is not known yet', () => {
    for (const unknown of [null, undefined, '']) {
      expect(canReadSalesData(unknown)).toBe(true)
    }
  })
})

describe('runIfSalesUser', () => {
  function pending() {
    let release
    const ready = new Promise((resolve) => (release = resolve))
    return { ready, release }
  }

  it('waits for the users list, then decides on the role it finds', async () => {
    let current = null // unknown until the users list has loaded
    const { ready, release } = pending()
    const action = vi.fn()

    const done = runIfSalesUser(ready, () => current, action)
    await Promise.resolve()
    expect(action).not.toHaveBeenCalled() // nothing is decided while it loads

    current = 'Compliance'
    release()
    await done
    expect(action).not.toHaveBeenCalled()
  })

  it('runs the action once the role turns out to be a sales role', async () => {
    let current = null
    const { ready, release } = pending()
    const action = vi.fn()

    const done = runIfSalesUser(ready, () => current, action)
    current = 'Sales User'
    release()
    await done
    expect(action).toHaveBeenCalledTimes(1)
  })

  it('runs the action when the users request fails (role stays unknown)', async () => {
    const action = vi.fn()
    await runIfSalesUser(Promise.reject(new Error('x')), () => null, action)
    expect(action).toHaveBeenCalledTimes(1)
  })
})

describe('what a Compliance-only user must not request on load', () => {
  beforeEach(() => {
    vi.resetModules()
    setActivePinia(createPinia())
    docResources = []
    listResources = []
    socket.on.mockClear()
    role = null // the layout builds its stores before the users list has loaded
  })

  // the users list arrives: the role becomes known, then the resource settles
  async function usersArrive(userRole) {
    role = userRole
    usersLoaded()
    await new Promise((resolve) => setTimeout(resolve))
  }

  async function settingsBeforeUsers() {
    const { getSettings } = await import('@/stores/settings')
    getSettings()
    getSettings() // every consumer calls it; the request goes out once
    return docResources[0]
  }

  it('does not read FCRM Settings (403: only sales roles may)', async () => {
    const settings = await settingsBeforeUsers()
    expect(settings.options.doctype).toBe('FCRM Settings')
    expect(settings.options.auto).toBe(false)
    expect(settings.reload).not.toHaveBeenCalled() // role unknown yet: wait
    await usersArrive('Compliance')
    expect(settings.reload).not.toHaveBeenCalled()
  })

  it('reads FCRM Settings once for a sales user, after the users list', async () => {
    const settings = await settingsBeforeUsers()
    expect(settings.reload).not.toHaveBeenCalled()
    await usersArrive('Sales User')
    expect(settings.reload).toHaveBeenCalledTimes(1)
  })

  async function availabilityBeforeUsers() {
    const { availabilityStore } = await import('@/stores/availability')
    availabilityStore()
    return listResources[0]
  }

  function fireSocketEvent(name) {
    socket.on.mock.calls.find(([event]) => event === name)[1]()
  }

  it('does not list the availability statuses (403) or reload them on a push', async () => {
    const statuses = await availabilityBeforeUsers()
    expect(statuses.options.doctype).toBe('CRM Availability Status')
    expect(statuses.options.auto).toBe(false)
    await usersArrive('Compliance')
    expect(statuses.fetch).not.toHaveBeenCalled()
    fireSocketEvent('crm_availability_statuses_updated')
    expect(statuses.reload).not.toHaveBeenCalled()
  })

  it('lists the availability statuses for a sales user once the users list is in, and reloads them on a push', async () => {
    const statuses = await availabilityBeforeUsers()
    expect(statuses.fetch).not.toHaveBeenCalled()
    await usersArrive('Sales Manager')
    expect(statuses.fetch).toHaveBeenCalledTimes(1)
    fireSocketEvent('crm_availability_statuses_updated')
    expect(statuses.reload).toHaveBeenCalledTimes(1)
  })
})
