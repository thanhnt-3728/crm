<template>
  <LayoutHeader>
    <template #left-header>
      <Breadcrumbs :items="breadcrumbs" />
    </template>
    <template #right-header>
      <template v-if="isFull">
        <Button
          v-if="can.edit && dirty"
          :label="__('Save')"
          :loading="busy"
          @click="saveForm"
        />
        <Button
          v-if="can.submit"
          variant="solid"
          :label="__('Submit for sign-off')"
          :loading="busy"
          @click="submit"
        />
        <Button
          v-if="can.approve"
          variant="solid"
          :label="__('Approve')"
          @click="showApprove = true"
        />
        <Button
          v-if="can.decline"
          theme="red"
          :label="__('Decline')"
          @click="showDecline = true"
        />
        <Button
          v-if="can.close"
          variant="solid"
          :label="__('Close request')"
          @click="showClose = true"
        />
      </template>
    </template>
  </LayoutHeader>

  <div
    v-if="request.loading && !request.data"
    class="flex h-full items-center justify-center"
  >
    <LoadingIndicator class="h-6 w-6 text-ink-gray-5" />
  </div>

  <div v-else-if="request.error" class="p-5">
    <ErrorMessage
      :message="
        request.error?.messages?.[0] || __('Could not load this request')
      "
    />
  </div>

  <div v-else-if="data" class="h-full overflow-y-auto">
    <div class="mx-auto flex max-w-4xl flex-col gap-6 p-5 text-ink-gray-8">
      <!-- Status and deadlines -->
      <div class="flex flex-wrap items-center gap-x-6 gap-y-2">
        <div class="text-2xl-semibold text-ink-gray-9">{{ data.name }}</div>
        <Badge
          variant="subtle"
          size="md"
          :theme="statusTheme(data.status)"
          :label="__(data.status)"
        />
        <div
          v-if="daysLeftLabel(data.days_left)"
          class="text-base"
          :class="data.days_left < 0 ? 'text-ink-red-4' : 'text-ink-gray-6'"
        >
          {{ daysLeftLabel(data.days_left) }}
        </div>
        <div class="text-base text-ink-gray-6">
          {{ __('Acknowledge by') }}:
          {{ formatDate(data.acknowledge_by, '', true) }}
        </div>
        <div class="text-base text-ink-gray-6">
          {{ __('Respond by') }}: {{ formatDate(data.respond_by, '', true) }}
        </div>
      </div>

      <div
        v-if="!isFull"
        class="rounded border px-4 py-3 text-p-base text-ink-gray-6"
      >
        {{
          __(
            'This request has been sent to Compliance. You can follow its status and deadlines here.',
          )
        }}
      </div>

      <template v-else>
        <!-- Erasure state -->
        <div
          v-if="doc.erasure_status === 'Queued'"
          class="flex items-center gap-2 rounded border bg-surface-gray-1 px-4 py-3 text-base"
        >
          <LoadingIndicator class="h-4 w-4" />
          {{ __('Erasing…') }}
        </div>
        <div
          v-else-if="doc.erasure_status === 'Failed'"
          class="rounded border border-outline-red-2 bg-surface-red-1 px-4 py-3 text-base text-ink-red-4"
          role="alert"
        >
          <div class="font-medium">{{ __('The erasure failed') }}</div>
          <div>{{ doc.erasure_error }}</div>
        </div>
        <div
          v-if="doc.status === 'Declined' && doc.decline_reason"
          class="rounded border px-4 py-3 text-base"
        >
          <div class="text-sm text-ink-gray-5">{{ __('Decline reason') }}</div>
          <div class="whitespace-pre-wrap">{{ doc.decline_reason }}</div>
        </div>

        <!-- Requester -->
        <section class="flex flex-col gap-3">
          <h3 class="text-lg-semibold text-ink-gray-9">
            {{ __('Requester') }}
          </h3>
          <div class="grid gap-3 sm:grid-cols-2">
            <FormControl
              v-model="form.requester_name"
              type="text"
              :label="__('Requester name')"
              :disabled="!can.edit"
            />
            <FormControl
              v-model="form.date_received"
              type="date"
              :label="__('Date received')"
              :disabled="!can.edit"
            />
            <FormControl
              v-model="form.arrived_via"
              type="select"
              :label="__('Arrived via')"
              :options="arrivedViaOptions"
              :disabled="!can.edit"
            />
            <FormControl
              v-model="form.other_names"
              type="textarea"
              :rows="2"
              :label="__('Other names')"
              :disabled="!can.edit"
            />
          </div>
          <FormControl
            v-model="form.original_message"
            type="textarea"
            :rows="4"
            :label="__('Original message')"
            :disabled="!can.edit"
          />
        </section>

        <!-- Identifiers -->
        <section class="flex flex-col gap-3">
          <h3 class="text-lg-semibold text-ink-gray-9">
            {{ __('Email addresses and phone numbers') }}
          </h3>
          <RequestIdentifiers
            :doc="doc"
            :usage="data.identifier_usage"
            :canEdit="can.edit"
            :busy="busy"
            @save="save"
          />
        </section>

        <!-- Matches -->
        <section class="flex flex-col gap-3">
          <h3 class="text-lg-semibold text-ink-gray-9">
            {{ __('Matching records') }}
          </h3>
          <RequestMatches
            :doc="doc"
            :canEdit="can.edit"
            :busy="busy"
            @save="save"
            @refresh="refreshMatches"
          />
        </section>

        <!-- Contracts -->
        <section v-if="isCompliance" class="flex flex-col gap-3">
          <h3 class="text-lg-semibold text-ink-gray-9">
            {{ __('Contract references') }}
          </h3>
          <FormControl
            v-model="form.contract_references"
            type="textarea"
            :rows="3"
            :disabled="!can.edit"
            :placeholder="__('Contracts that must be kept, one per line')"
          />
        </section>

        <!-- Checklist -->
        <section class="flex flex-col gap-3">
          <h3 class="text-lg-semibold text-ink-gray-9">
            {{ __('Checklist') }}
          </h3>
          <RequestChecklist
            :doc="doc"
            :canManage="can.manage_checklist"
            :busy="busy"
            @save="save"
          />
        </section>

        <!-- Acknowledgment -->
        <section class="flex flex-col gap-3">
          <h3 class="text-lg-semibold text-ink-gray-9">
            {{ __('Acknowledgment') }}
          </h3>
          <div class="flex flex-wrap items-end gap-4">
            <FormControl
              type="checkbox"
              :label="__('Acknowledgment sent')"
              :modelValue="!!doc.acknowledgment_sent"
              :disabled="!can.manage_checklist || busy"
              @update:modelValue="
                (value) => save({ acknowledgment_sent: value ? 1 : 0 })
              "
            />
            <FormControl
              type="date"
              class="w-48"
              :label="__('Acknowledged on')"
              :modelValue="doc.acknowledged_on || ''"
              :disabled="!can.manage_checklist || busy"
              @update:modelValue="
                (value) => save({ acknowledged_on: value || null })
              "
            />
          </div>
        </section>

        <!-- Emails -->
        <section class="flex flex-col gap-3">
          <h3 class="text-lg-semibold text-ink-gray-9">
            {{ __('Emails') }}
          </h3>
          <div
            v-if="!data.emails.length"
            class="rounded border border-dashed px-3 py-4 text-p-base text-ink-gray-5"
          >
            {{ __('No emails attached to this request.') }}
          </div>
          <ul v-else class="divide-y rounded border">
            <li
              v-for="email in data.emails"
              :key="email.name"
              class="flex items-center justify-between gap-3 px-3 py-2 text-base"
            >
              <div class="min-w-0">
                <div class="truncate text-ink-gray-9">
                  {{ email.subject || __('(no subject)') }}
                </div>
                <div class="truncate text-sm text-ink-gray-5">
                  {{ email.sender }}
                </div>
              </div>
              <div class="shrink-0 text-sm text-ink-gray-5">
                {{ formatDate(email.communication_date) }}
              </div>
            </li>
          </ul>
        </section>
      </template>
    </div>
  </div>

  <template v-if="isFull">
    <DeclineRequestDialog
      v-model="showDecline"
      :requestName="requestId"
      @done="onDialogResult"
    />
    <CloseRequestDialog
      v-model="showClose"
      :requestName="requestId"
      :declined="data.status === 'Declined'"
      @done="onDialogResult"
    />
    <!-- Approval hands back the refreshed request (Queued, or On Hold). Not
         resetForm: unsaved edits survive, as with table saves. -->
    <ApproveErasureModal
      v-model="showApprove"
      :requestName="requestId"
      @approved="onResult"
    />
  </template>
</template>

<script setup>
import ApproveErasureModal from '@/components/Privacy/ApproveErasureModal.vue'
import CloseRequestDialog from '@/components/Privacy/CloseRequestDialog.vue'
import DeclineRequestDialog from '@/components/Privacy/DeclineRequestDialog.vue'
import RequestChecklist from '@/components/Privacy/RequestChecklist.vue'
import RequestIdentifiers from '@/components/Privacy/RequestIdentifiers.vue'
import RequestMatches from '@/components/Privacy/RequestMatches.vue'
import LayoutHeader from '@/components/LayoutHeader.vue'
import { formatDate } from '@/utils'
import {
  changedFields,
  daysLeftLabel,
  mergeForm,
  statusTheme,
} from '@/utils/erasureRequest'
import {
  Badge,
  Breadcrumbs,
  Button,
  LoadingIndicator,
  call,
  createResource,
  toast,
} from 'frappe-ui'
import { computed, onBeforeUnmount, reactive, ref, watch } from 'vue'

const props = defineProps({
  requestId: { type: String, required: true },
})

const POLL_MS = 3000
const FORM_KEYS = [
  'requester_name',
  'date_received',
  'arrived_via',
  'other_names',
  'original_message',
  'contract_references',
]

const request = createResource({
  url: 'crm.privacy.api.get_request',
  makeParams: () => ({ name: props.requestId }),
  auto: true,
})

const data = computed(() => request.data)
const isFull = computed(() => data.value?.access === 'full')
const doc = computed(() => data.value?.doc || {})
const can = computed(() => data.value?.can || {})
// Only Compliance holds these rights, so they stand in for the role.
const isCompliance = computed(
  () =>
    !!(
      can.value.manage_checklist ||
      can.value.decline ||
      can.value.close ||
      can.value.approve
    ),
)

const busy = ref(false)
const showApprove = ref(false)
const showDecline = ref(false)
const showClose = ref(false)

const breadcrumbs = computed(() => [
  {
    label: __('Erasure requests'),
    route: { name: 'Erasure Requests' },
  },
  {
    label: props.requestId,
    route: { name: 'Erasure Request', params: { requestId: props.requestId } },
  },
])

const arrivedViaOptions = ['Email', 'Phone', 'Web form', 'Mail', 'Other'].map(
  (value) => ({ label: __(value), value }),
)

// Editable copy of the plain fields; tables and ticks save on their own.
const form = reactive(Object.fromEntries(FORM_KEYS.map((key) => [key, ''])))

const formKeys = computed(() =>
  FORM_KEYS.filter(
    (key) => key !== 'contract_references' || isCompliance.value,
  ),
)
const changedValues = computed(() =>
  changedFields(form, doc.value, formKeys.value),
)
const dirty = computed(() => Object.keys(changedValues.value).length > 0)

// The doc values the form was last synced to, and which request they belong to.
let baseline = {}
let syncedName = null

function snapshot() {
  baseline = Object.fromEntries(
    FORM_KEYS.map((key) => [key, doc.value[key] ?? '']),
  )
  syncedName = doc.value.name ?? null
}

// Drop unsaved edits and show the saved doc (a different request, or after the
// request moved on through Decline or Close).
function resetForm() {
  for (const key of FORM_KEYS) form[key] = doc.value[key] ?? ''
  snapshot()
}

// A refreshed doc (table save, polling) must not overwrite what the user is
// typing: only fields they have not touched take the saved value.
watch(
  doc,
  () => {
    if (doc.value.name !== syncedName) return resetForm()
    Object.assign(form, mergeForm(form, baseline, doc.value, FORM_KEYS))
    snapshot()
  },
  { immediate: true },
)

watch(
  () => props.requestId,
  () => request.reload(),
)

function showError(error) {
  toast.error(
    error?.messages?.[0] || error?.message || __('Something went wrong'),
  )
}

// Apply a refreshed request. Unsaved form edits survive; the doc watcher merges.
function onResult(result) {
  request.setData(result)
}

// Decline and Close end the editing session, so start the form over.
function onDialogResult(result) {
  onResult(result)
  resetForm()
}

async function run(method, params) {
  busy.value = true
  try {
    const result = await call(method, { name: props.requestId, ...params })
    onResult(result)
    return true
  } catch (error) {
    showError(error)
    return false
  } finally {
    busy.value = false
  }
}

function save(values) {
  return run('crm.privacy.api.save_request', { values })
}

function saveForm() {
  if (!dirty.value) return Promise.resolve(true)
  return save(changedValues.value)
}

function refreshMatches() {
  return run('crm.privacy.api.refresh_request_matches')
}

async function submit() {
  if (!(await saveForm())) return
  await run('crm.privacy.api.submit_request')
}

// Poll while the erasure job runs.
let timer = null
function stopPolling() {
  if (timer) clearInterval(timer)
  timer = null
}
watch(
  () => doc.value.erasure_status,
  (status) => {
    stopPolling()
    if (status === 'Queued') timer = setInterval(request.reload, POLL_MS)
  },
  { immediate: true },
)
onBeforeUnmount(stopPolling)
</script>
