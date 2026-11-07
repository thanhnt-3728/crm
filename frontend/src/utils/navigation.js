import ContactsIcon from '@/components/Icons/ContactsIcon.vue'
import DealsIcon from '@/components/Icons/DealsIcon.vue'
import LeadsIcon from '@/components/Icons/LeadsIcon.vue'
import NoteIcon from '@/components/Icons/NoteIcon.vue'
import OrganizationsIcon from '@/components/Icons/OrganizationsIcon.vue'
import PhoneIcon from '@/components/Icons/PhoneIcon.vue'
import TaskIcon from '@/components/Icons/TaskIcon.vue'
import LucideLayoutDashboard from '~icons/lucide/layout-dashboard'
import LucideShieldCheck from '~icons/lucide/shield-check'
import router from '@/router'

export const navigationItems = [
  {
    label: 'Dashboard',
    icon: LucideLayoutDashboard,
    route: 'Dashboard',
    desktopOnly: true,
  },
  { label: 'Leads', icon: LeadsIcon, route: 'Leads' },
  { label: 'Deals', icon: DealsIcon, route: 'Deals' },
  { label: 'Contacts', icon: ContactsIcon, route: 'Contacts' },
  { label: 'Organizations', icon: OrganizationsIcon, route: 'Organizations' },
  { label: 'Notes', icon: NoteIcon, route: 'Notes' },
  { label: 'Tasks', icon: TaskIcon, route: 'Tasks' },
  { label: 'Call Logs', icon: PhoneIcon, route: 'Call Logs' },
  {
    label: 'Erasure requests',
    icon: LucideShieldCheck,
    route: 'ErasureRequests',
    desktopOnly: true, // mobile pages are a follow-up
    complianceOnlyUser: true, // the one page a user with only the Compliance role can use
  },
]

// `role` is the user's top CRM role. A user whose only role is Compliance has
// no access to leads, deals or the other lists, so they get just their page.
export function getNavigationItems({ mobile = false, role = '' } = {}) {
  return navigationItems.filter(
    (item) =>
      router.hasRoute(item.route) &&
      (!mobile || !item.desktopOnly) &&
      (role !== 'Compliance' || item.complianceOnlyUser),
  )
}
