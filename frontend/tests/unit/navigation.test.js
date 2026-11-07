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

describe('navigation for a Compliance-only user', () => {
  it('shows only the pages that user can use', () => {
    const routes = getNavigationItems({ role: 'Compliance' }).map(
      (item) => item.route,
    )
    expect(routes).toEqual(['ErasureRequests'])
  })

  it('leaves every other role with the full list', () => {
    const all = getNavigationItems().map((item) => item.route)
    for (const role of ['System Manager', 'Sales Manager', 'Sales User']) {
      const routes = getNavigationItems({ role }).map((item) => item.route)
      expect(routes).toEqual(all)
    }
    expect(all).toContain('Leads')
    expect(all).toContain('ErasureRequests')
  })
})
