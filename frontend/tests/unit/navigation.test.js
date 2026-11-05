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

  it('lists privacy requests for every user on desktop', () => {
    const routes = getNavigationItems().map((item) => item.route)
    expect(routes).toContain('ErasureRequests')
    // the item takes no role switch: the server decides what each user sees
    expect(
      navigationItems.find((item) => item.route === 'ErasureRequests'),
    ).not.toHaveProperty('privacyOnly')
  })
})
