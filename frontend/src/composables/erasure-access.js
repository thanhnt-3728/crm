import { createResource } from 'frappe-ui'
import { computed } from 'vue'

// Role flags for the erasure UI. These only decide what is shown; the server
// enforces every rule. Roles are fetched once per page load, never stored.
export const PRIVACY_OFFICER = 'Privacy Officer'
export const ERASURE_REQUEST_ROLES = [
  'System Manager',
  'Sales Manager',
  'Sales User',
  PRIVACY_OFFICER,
]
// Mirrors the doctype's create permission: Sales Manager is read-only there.
const LOG_ROLES = ['System Manager', 'Sales User']

const rolesResource = createResource({
  url: 'frappe.core.doctype.user.user.get_current_user_roles',
  auto: false,
})

export function useErasureAccess() {
  if (!rolesResource.data && !rolesResource.loading && !rolesResource.error) {
    rolesResource.fetch()
  }
  const roles = computed(() => rolesResource.data || [])
  const hasAny = (wanted) => roles.value.some((role) => wanted.includes(role))
  return {
    roles,
    isPrivacyOfficer: computed(() => roles.value.includes(PRIVACY_OFFICER)),
    canLog: computed(() => hasAny(LOG_ROLES)),
    canRead: computed(() => hasAny(ERASURE_REQUEST_ROLES)),
  }
}
