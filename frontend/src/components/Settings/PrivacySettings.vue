<template>
  <div class="flex h-full flex-col gap-6 py-8 px-6 text-ink-gray-8">
    <div class="flex justify-between px-2 text-ink-gray-8">
      <div class="flex flex-col gap-1">
        <h2 class="flex gap-2 text-2xl-semibold leading-none h-5">
          {{ __('Privacy') }}
        </h2>
        <p class="text-p-base text-ink-gray-6">
          {{
            __(
              'Set who handles erasure requests, how long contract records are kept, and which fields hold personal data.',
            )
          }}
        </p>
      </div>
      <div class="flex item-center space-x-2 w-3/12 justify-end">
        <Button
          v-if="isDirty"
          :label="__('Save')"
          variant="solid"
          :loading="settings.save.loading"
          @click="saveSettings"
        />
      </div>
    </div>

    <div v-if="settings.doc" class="flex flex-1 flex-col overflow-y-auto">
      <div class="flex items-center justify-between gap-4 py-3 px-2">
        <div class="flex flex-col">
          <div class="text-p-base-medium text-ink-gray-7 truncate">
            {{ __('Head of Compliance') }}
          </div>
          <div class="text-p-sm text-ink-gray-5">
            {{
              __('Receives the day-40 reminder for every open erasure request')
            }}
          </div>
        </div>
        <div class="w-56">
          <Link v-model="settings.doc.head_of_compliance" doctype="User" />
        </div>
      </div>
      <div class="h-px border-t mx-2 border-outline-elevation-2" />
      <div class="flex items-center justify-between gap-4 py-3 px-2">
        <div class="flex flex-col">
          <div class="text-p-base-medium text-ink-gray-7 truncate">
            {{ __('Contract retention period (months)') }}
          </div>
          <div class="text-p-sm text-ink-gray-5">
            {{
              __(
                'How long the entry for a retained contract is kept after the erasure',
              )
            }}
          </div>
        </div>
        <div class="w-24">
          <FormControl
            v-model="settings.doc.contract_retention_months"
            type="number"
            min="0"
          />
        </div>
      </div>
      <div class="h-px border-t mx-2 border-outline-elevation-2" />
      <div class="flex flex-col gap-3 py-3 px-2">
        <div class="flex flex-col">
          <div class="text-p-base-medium text-ink-gray-7 truncate">
            {{ __('Personal fields') }}
          </div>
          <div class="text-p-sm text-ink-gray-5">
            {{
              __(
                'Extra fields an erasure request scrubs. Names, emails and phone numbers are always erased, listed or not. Report fields such as status, owner, organization and deal value cannot be listed.',
              )
            }}
          </div>
        </div>
        <div
          v-if="!rows.length"
          class="rounded border border-dashed px-3 py-4 text-p-base text-ink-gray-5"
        >
          {{ __('No personal fields listed.') }}
        </div>
        <ul v-else class="flex flex-col gap-2">
          <li
            v-for="(row, index) in rows"
            :key="row.name || `new-${index}`"
            class="flex items-center gap-2"
          >
            <FormControl
              v-model="row.document_type"
              type="select"
              class="w-48 shrink-0"
              :options="documentTypeOptions"
              :aria-label="__('Document type')"
            />
            <FormControl
              v-model="row.fieldname"
              type="text"
              class="flex-1"
              :placeholder="__('Fieldname')"
              :aria-label="__('Fieldname')"
            />
            <Button
              variant="ghost"
              icon="lucide-trash-2"
              :aria-label="__('Remove')"
              @click="removeRow(index)"
            />
          </li>
        </ul>
        <div>
          <Button
            :label="__('Add field')"
            iconLeft="lucide-plus"
            @click="addRow"
          />
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import Link from '@/components/Controls/Link.vue'
import { Button, FormControl, toast, createDocumentResource } from 'frappe-ui'
import { computed } from 'vue'

const DOCTYPE = 'CRM Privacy Settings'

const DOCUMENT_TYPES = [
  'CRM Lead',
  'CRM Deal',
  'Contact',
  'Contact Email',
  'Contact Phone',
  'CRM Contacts',
]

const documentTypeOptions = DOCUMENT_TYPES.map((value) => ({
  label: value,
  value,
}))

const settings = createDocumentResource({
  doctype: DOCTYPE,
  name: DOCTYPE,
  auto: true,
})

const isDirty = computed(
  () => JSON.stringify(settings.doc) !== JSON.stringify(settings.originalDoc),
)

const rows = computed(() => settings.doc?.personal_fields || [])

function addRow() {
  if (!settings.doc.personal_fields) settings.doc.personal_fields = []
  settings.doc.personal_fields.push({
    document_type: DOCUMENT_TYPES[0],
    fieldname: '',
  })
}

function removeRow(index) {
  settings.doc.personal_fields.splice(index, 1)
}

function validate() {
  const months = Number(settings.doc.contract_retention_months)
  if (!Number.isInteger(months) || months < 0) {
    return __('Contract retention period must be a whole number of months')
  }
  if (!settings.doc.personal_fields?.length) {
    return __('List at least one personal field')
  }
  const seen = new Set()
  for (const row of settings.doc.personal_fields || []) {
    const fieldname = (row.fieldname || '').trim()
    if (!fieldname) return __('Every personal field needs a fieldname')
    const key = `${row.document_type}:${fieldname}`
    if (seen.has(key)) {
      return __('{0} is listed twice', [`${row.document_type} ${fieldname}`])
    }
    seen.add(key)
  }
  return ''
}

function saveSettings() {
  const problem = validate()
  if (problem) return toast.error(problem)

  settings.doc.contract_retention_months = Number(
    settings.doc.contract_retention_months,
  )
  for (const row of settings.doc.personal_fields || []) {
    row.fieldname = row.fieldname.trim()
  }
  settings.save.submit(null, {
    onSuccess: () => {
      toast.success(__('Privacy settings updated'))
    },
    onError(error) {
      toast.error(error?.messages?.[0] || __('Failed to save settings'))
    },
  })
}
</script>
