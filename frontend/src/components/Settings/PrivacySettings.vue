<template>
  <div class="flex h-full flex-col gap-6 py-8 px-6 text-ink-gray-8">
    <div class="flex justify-between px-2">
      <div class="flex flex-col gap-1">
        <div class="flex items-center gap-2">
          <h2 class="flex gap-2 text-2xl-semibold leading-none h-5">
            {{ __('Privacy') }}
          </h2>
          <Badge v-if="isDirty" :label="__('Not Saved')" theme="amber" />
        </div>
        <p class="text-p-base text-ink-gray-6">
          {{
            __(
              'Who answers privacy requests, how long contract entries are kept, and which fields hold personal data.',
            )
          }}
        </p>
      </div>
      <div class="flex item-center space-x-2 w-3/12 justify-end">
        <Button
          v-if="isDirty"
          :label="__('Save')"
          variant="solid"
          :loading="saving"
          @click="save"
        />
      </div>
    </div>

    <div v-if="loading" class="flex flex-1 items-center justify-center">
      <LoadingIndicator class="size-8" />
    </div>
    <div v-else-if="loadError" class="px-2">
      <ErrorMessage :message="loadError" />
    </div>
    <div v-else class="flex-1 flex flex-col overflow-y-auto">
      <div class="flex items-center justify-between gap-4 py-3 px-2">
        <div class="flex flex-col">
          <div class="text-p-base-medium text-ink-gray-7 truncate">
            {{ __('Head of Compliance') }}
          </div>
          <div class="text-p-sm text-ink-gray-5">
            {{
              __(
                'Alerted when a request reaches day 40 without an answer. Compliance users are reminded earlier.',
              )
            }}
          </div>
        </div>
        <div class="w-60">
          <Link v-model="headOfCompliance" doctype="User" />
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
                'How long the name and contract reference of a person are kept under the signed-contract exception. 0 keeps them until counsel sets a period.',
              )
            }}
          </div>
        </div>
        <div class="w-28">
          <FormControl
            v-model="contractRetentionMonths"
            type="number"
            min="0"
          />
        </div>
      </div>
      <div class="h-px border-t mx-2 border-outline-elevation-2" />

      <div class="flex flex-col gap-1 py-3 px-2">
        <div class="text-p-base-medium text-ink-gray-7">
          {{ __('Personal fields') }}
        </div>
        <div class="text-p-sm text-ink-gray-5">
          {{
            __(
              'Erasure clears these fields on every matched record. A custom field that is not listed here is flagged for review when a request is approved.',
            )
          }}
        </div>
      </div>

      <div
        v-for="doctype in doctypes"
        :key="doctype"
        class="flex flex-col gap-2 px-2 pb-4"
      >
        <div class="text-sm-medium text-ink-gray-7">
          {{ __(doctype) }}
        </div>
        <div
          v-for="row in rowsOf(doctype)"
          :key="row.id"
          class="flex items-center gap-2"
        >
          <FormControl
            v-model="row.fieldname"
            type="select"
            class="flex-1"
            :options="choicesFor(row)"
            :placeholder="__('Select a field')"
          />
          <Button
            variant="ghost"
            icon="lucide-x"
            :tooltip="__('Remove')"
            @click="removeRow(row)"
          />
        </div>
        <div v-if="!rowsOf(doctype).length" class="text-sm text-ink-gray-5">
          {{ __('No fields listed') }}
        </div>
        <div>
          <Button
            variant="subtle"
            size="sm"
            icon-left="lucide-plus"
            :label="__('Add field')"
            @click="addRow(doctype)"
          />
        </div>
      </div>
    </div>

    <ErrorMessage v-if="!loading && !loadError" :message="saveError" />
  </div>
</template>

<script setup>
import Link from '@/components/Controls/Link.vue'
import { getMeta } from '@/stores/meta'
import {
  buildSettingsPayload,
  errorText,
  PERSONAL_FIELD_DOCTYPES,
  personalFieldChoices,
} from '@/utils/erasureRequest'
import {
  Badge,
  Button,
  call,
  ErrorMessage,
  FormControl,
  LoadingIndicator,
  toast,
} from 'frappe-ui'
import { computed, onMounted, ref } from 'vue'

const doctypes = PERSONAL_FIELD_DOCTYPES
// One meta per document type; each loads once and is shared app-wide.
const metas = Object.fromEntries(doctypes.map((dt) => [dt, getMeta(dt)]))

const headOfCompliance = ref('')
const contractRetentionMonths = ref(0)
const rows = ref([])
const saved = ref('')
const loading = ref(true)
const loadError = ref('')
const saving = ref(false)
const saveError = ref('')

let nextId = 0

function toForm(settings) {
  headOfCompliance.value = settings.head_of_compliance || ''
  contractRetentionMonths.value = settings.contract_retention_months || 0
  rows.value = (settings.personal_fields || []).map((row) => ({
    id: nextId++,
    document_type: row.document_type,
    fieldname: row.fieldname,
  }))
  saved.value = snapshot()
}

function payload() {
  return buildSettingsPayload({
    headOfCompliance: headOfCompliance.value,
    contractRetentionMonths: contractRetentionMonths.value,
    personalFields: rows.value,
  })
}

function snapshot() {
  return JSON.stringify(payload())
}

const isDirty = computed(() => !loading.value && snapshot() !== saved.value)

onMounted(async () => {
  try {
    toForm(await call('crm.api.erasure.get_privacy_settings'))
  } catch (e) {
    loadError.value = errorText(e)
  } finally {
    loading.value = false
  }
})

function rowsOf(doctype) {
  return rows.value.filter((row) => row.document_type === doctype)
}

function choicesFor(row) {
  const fields = metas[row.document_type]?.getFields() || []
  return personalFieldChoices(fields, rows.value, row)
}

function addRow(doctype) {
  rows.value.push({ id: nextId++, document_type: doctype, fieldname: '' })
}

function removeRow(row) {
  rows.value = rows.value.filter((other) => other !== row)
}

async function save() {
  saving.value = true
  saveError.value = ''
  try {
    toForm(await call('crm.api.erasure.save_privacy_settings', payload()))
    toast.success(__('Privacy settings saved'))
  } catch (e) {
    saveError.value = errorText(e)
  } finally {
    saving.value = false
  }
}
</script>
