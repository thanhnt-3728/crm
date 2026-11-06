import ContactsIcon from '@/components/Icons/ContactsIcon.vue'
import DealsIcon from '@/components/Icons/DealsIcon.vue'
import LeadsIcon from '@/components/Icons/LeadsIcon.vue'
import NoteIcon from '@/components/Icons/NoteIcon.vue'
import OrganizationsIcon from '@/components/Icons/OrganizationsIcon.vue'
import PhoneIcon from '@/components/Icons/PhoneIcon.vue'
import TaskIcon from '@/components/Icons/TaskIcon.vue'
import LucideLayoutDashboard from '~icons/lucide/layout-dashboard'
import LucideShieldCheck from '~icons/lucide/shield-check'
import { ERASURE_REQUEST_ROLES } from '@/composables/erasure-access'
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
    label: 'Erasure Requests',
    icon: LucideShieldCheck,
    route: 'Erasure Requests',
    roles: ERASURE_REQUEST_ROLES,
  },
]

// `roles` (the user's roles) hides items restricted to other roles; omit it to skip that check.
export function getNavigationItems({ mobile = false, roles } = {}) {
  return navigationItems.filter(
    (item) =>
      router.hasRoute(item.route) &&
      (!mobile || !item.desktopOnly) &&
      (!item.roles || !roles || item.roles.some((role) => roles.includes(role))),
  )
}
