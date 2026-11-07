import { createDocumentResource } from 'frappe-ui'
import { usersStore } from '@/stores/users'
import { runIfSalesUser } from '@/utils/salesAccess'
import { reactive, ref } from 'vue'

const settings = ref({})
const brand = reactive({})

const _settings = createDocumentResource({
  doctype: 'FCRM Settings',
  name: 'FCRM Settings',
  auto: false, // fetched by `getSettings`, which skips it for a Compliance-only user (403)
  onSuccess: (data) => {
    settings.value = data
    getSettings().setupBrand()
    return data
  },
})

let requested = false

export function getSettings() {
  if (!requested) {
    requested = true
    const { users, getUserRole } = usersStore()
    runIfSalesUser(users.promise, getUserRole, () => _settings.reload())
  }

  function setupBrand() {
    brand.name = settings.value?.brand_name
    brand.logo = settings.value?.brand_logo
    brand.favicon = settings.value?.favicon
  }

  return {
    _settings,
    settings,
    brand,
    setupBrand,
  }
}
