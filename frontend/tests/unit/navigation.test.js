import { getNavigationItems, navigationItems } from '@/utils/navigation'

describe('navigationItems', () => {
  it('uses unique route names', () => {
    const routes = navigationItems.map((item) => item.route)
    expect(new Set(routes).size).toBe(routes.length)
  })

  it('omits desktop-only destinations on mobile', () => {
    const mobileRoutes = getNavigationItems({ mobile: true }).map(
      (item) => item.route,
    )
    expect(mobileRoutes).not.toContain('Dashboard')
    expect(mobileRoutes).not.toContain('Calendar')
    expect(mobileRoutes).toContain('Leads')
  })
})

describe('erasure requests item', () => {
  const routes = (options) => getNavigationItems(options).map((i) => i.route)

  it('points at a registered route', () => {
    expect(routes()).toContain('Erasure Requests')
  })

  it('is shown to roles with access and hidden from others once roles are known', () => {
    expect(routes({ roles: ['Privacy Officer'] })).toContain('Erasure Requests')
    expect(routes({ roles: ['Sales User'] })).toContain('Erasure Requests')
    expect(routes({ roles: ['Guest'] })).not.toContain('Erasure Requests')
    expect(routes({ roles: [] })).not.toContain('Erasure Requests')
  })

  it('keeps unrestricted items regardless of roles', () => {
    expect(routes({ roles: [] })).toContain('Leads')
  })
})
