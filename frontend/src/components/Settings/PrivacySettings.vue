<template>
  <div class="flex h-full flex-col gap-6 px-6 py-8 text-ink-gray-8">
    <div class="flex items-start justify-between gap-4 px-2">
      <div class="flex flex-col gap-1">
        <h2 class="flex h-5 gap-2 text-2xl-semibold leading-none">
          {{ __('Privacy') }}
        </h2>
        <p class="text-p-base text-ink-gray-6">
          {{
            __(
              'Who handles personal data erasure requests, and which fields are erased.',
            )
          }}
        </p>
      </div>
      <Button
        v-if="loaded"
        variant="solid"
        :label="__('Save')"
        :loading="saving"
        :disabled="!dirty"
        @click="save"
      />
    </div>

    <div v-if="!loaded" class="flex justify-center p-8">
      <ErrorMessage v-if="loadError" :message="loadError" />
      <LoadingIndicator v-else class="size-6" />
    </div>
    <div v-else class="flex flex-1 flex-col gap-8 overflow-y-auto px-2">
      <Alert
        v-if="!secretAvailable"
        theme="red"
        :title="__('The do-not-contact secret is missing')"
        :description="
          __(
            'Erased people cannot be checked against new leads and emails, and saving some records fails. Restore the CRM Privacy Settings secret and the site encryption key from a backup. Do not create a new one: it would orphan every block.',
          )
        "
      />
      <section class="flex flex-col gap-3">
        <h3 class="text-lg-medium">{{ __('Compliance') }}</h3>
        <Link
          v-model="form.head_of_compliance"
          :label="__('Head of Compliance')"
          doctype="User"
          :filters="{ enabled: 1, user_type: 'System User' }"
          hide-me
        />
        <p class="-mt-2 text-p-sm text-ink-gray-5">
          {{
            __(
              'Receives the day-40 escalation for requests that are still open',
            )
          }}
        </p>
        <FormControl
          v-model="form.contract_retention_months"
          type="number"
          :min="0"
          :label="__('Contract retention period (months)')"
        />
        <p class="-mt-2 text-p-sm text-ink-gray-5">
          {{
            __(
              'How long a signed contract or order keeps the name and contract reference. Set it per counsel. It must be above 0 before a request with contract references can be approved.',
            )
          }}
        </p>
      </section>
      <section class="flex flex-col gap-3">
        <h3 class="text-lg-medium">{{ __('Compliance members') }}</h3>
        <ComplianceMembers v-model="members" />
      </section>
      <section class="flex flex-col gap-3">
        <div>
          <h3 class="text-lg-medium">{{ __('Personal fields') }}</h3>
          <p class="text-p-sm text-ink-gray-5">
            {{
              __(
                'Fields blanked on erasure. Add custom fields that identify a person. Fields that reports group by cannot be listed.',
              )
            }}
          </p>
        </div>
        <PersonalFieldsTable
          v-model="form.personal_fields"
          :document-types="documentTypes"
        />
      </section>
    </div>
  </div>
</template>

<script setup>
import Link from '@/components/Controls/Link.vue'
import { erasureCall, runAction } from '@/components/ErasureRequests/erasureApi'
import ComplianceMembers from '@/components/Settings/ComplianceMembers.vue'
import PersonalFieldsTable from '@/components/Settings/PersonalFieldsTable.vue'
import { errorText } from '@/utils/erasureRequestDisplay'
import {
  Alert,
  ErrorMessage,
  FormControl,
  LoadingIndicator,
  toast,
} from 'frappe-ui'
import { computed, onMounted, reactive, ref } from 'vue'

const loaded = ref(false)
const loadError = ref('')
const saving = ref(false)
const secretAvailable = ref(true)
const documentTypes = ref([])
const members = ref([])
const form = reactive({
  head_of_compliance: '',
  contract_retention_months: 0,
  personal_fields: [],
})
let saved = ''

const snapshot = () =>
  JSON.stringify([
    form.head_of_compliance || '',
    Number(form.contract_retention_months) || 0,
    form.personal_fields,
  ])
const dirty = computed(() => snapshot() !== saved)

function apply(data) {
  form.head_of_compliance = data.head_of_compliance || ''
  form.contract_retention_months = data.contract_retention_months || 0
  form.personal_fields = data.personal_fields.map(
    ({ document_type, fieldname }) => ({ document_type, fieldname }),
  )
  documentTypes.value = data.document_types
  secretAvailable.value = data.secret_available
  members.value = data.members
  saved = snapshot()
}

onMounted(async () => {
  try {
    apply(await erasureCall('settings.get_privacy_settings'))
    loaded.value = true
  } catch (error) {
    loadError.value = errorText(error)
  }
})

async function save() {
  if (form.personal_fields.some((row) => !row.fieldname)) {
    toast.error(__('Choose a field for every personal-field row'))
    return
  }
  saving.value = true
  const data = await runAction('settings.save_privacy_settings', {
    head_of_compliance: form.head_of_compliance || null,
    contract_retention_months: Number(form.contract_retention_months) || 0,
    personal_fields: form.personal_fields,
  })
  saving.value = false
  if (!data) return
  apply(data)
  toast.success(__('Privacy settings saved'))
}
</script>
