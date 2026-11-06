<template>
  <LayoutHeader>
    <template #left-header>
      <Breadcrumbs :items="breadcrumbs" />
    </template>
    <template v-if="request.data" #right-header>
      <ErasureRequestActions
        :actions="actions"
        @submit="act('submit_for_approval', __('Request submitted'))"
        @approve="showApprove = true"
        @reject="showReject = true"
        @close="act('close', __('Request closed'))"
        @retry="retry"
      />
    </template>
  </LayoutHeader>
  <div v-if="doc.name" class="h-full overflow-auto p-5">
    <div class="mb-4 flex items-center gap-2">
      <span class="text-lg font-semibold text-ink-gray-9">{{
        doc.subject_name
      }}</span>
      <Badge :label="__(doc.status)" />
    </div>
    <ErasureRequestDates
      :request="doc"
      :can-acknowledge="acknowledgeable"
      @acknowledge="saveAcknowledged"
    />
    <ErasureRequestNotices :request="doc" :stalled="stalled" />
    <h3 class="mb-2 mt-6 font-medium text-ink-gray-8">{{ __('Records') }}</h3>
    <ErasureMatchesList
      v-if="preview.data"
      :groups="preview.data.groups"
      :hidden="preview.data.hidden"
    />
    <div v-else-if="preview.error" class="text-p-sm text-ink-gray-5">
      {{
        __('Matched records are visible to the requester and Privacy Officers.')
      }}
    </div>
    <ErasureOutcome :request="doc" />
  </div>
  <ErrorMessage
    v-else-if="request.error"
    class="p-5"
    :message="serverMessage(request.error, __('Could not load the request'))"
  />
  <ApproveErasureDialog
    v-model="showApprove"
    :request-name="name"
    @approved="reload"
  />
  <RejectErasureDialog
    v-model="showReject"
    :request-name="name"
    @rejected="reload"
  />
</template>

<script setup>
import {
  Badge,
  Breadcrumbs,
  ErrorMessage,
  call,
  createResource,
  toast,
} from 'frappe-ui'
import { computed, ref } from 'vue'
import ApproveErasureDialog from '@/components/Erasure/approve-erasure-dialog.vue'
import ErasureRequestActions from '@/components/Erasure/erasure-request-actions.vue'
import ErasureRequestDates from '@/components/Erasure/erasure-request-dates.vue'
import ErasureRequestNotices from '@/components/Erasure/erasure-request-notices.vue'
import ErasureOutcome from '@/components/Erasure/erasure-outcome.vue'
import ErasureMatchesList from '@/components/Erasure/erasure-matches-list.vue'
import RejectErasureDialog from '@/components/Erasure/reject-erasure-dialog.vue'
import LayoutHeader from '@/components/LayoutHeader.vue'
import { useErasureAccess } from '@/composables/erasure-access'
import { useExecutionWatch } from '@/composables/erasure-execution-watch'
import { sessionStore } from '@/stores/session'
import {
  REQUEST_DETAIL_FIELDS,
  availableActions,
  canAcknowledge,
} from '@/utils/erasure-actions'
import { serverMessage } from '@/utils/erasure-matches'

const props = defineProps({ name: { type: String, required: true } })

const { user } = sessionStore()
const { isPrivacyOfficer } = useErasureAccess()
const showApprove = ref(false)
const showReject = ref(false)

// Header fields only: the child table of matches is never loaded here, because
// it would expose records the viewer may not read. Matches come from get_preview.
const request = createResource({
  url: 'frappe.client.get_list',
  params: {
    doctype: 'CRM Erasure Request',
    fields: REQUEST_DETAIL_FIELDS,
    filters: { name: props.name },
    limit_page_length: 1,
  },
  auto: true,
  onError: (e) =>
    toast.error(serverMessage(e, __('Could not load the request'))),
})
// Refused for users who are neither the requester nor a Privacy Officer.
const preview = createResource({
  url: 'crm.api.erasure.get_preview',
  params: { name: props.name },
  auto: true,
})

const doc = computed(() => request.data?.[0] || {})
const { stalled } = useExecutionWatch(
  doc,
  () => request.reload(),
  () => preview.reload(),
)
const isRequester = computed(() => doc.value.requested_by === user)
const actions = computed(() =>
  availableActions({
    status: doc.value.status,
    isPrivacyOfficer: isPrivacyOfficer.value,
    isRequester: isRequester.value,
    lastError: doc.value.last_error,
    stalled: stalled.value,
  }),
)
const acknowledgeable = computed(() =>
  canAcknowledge({
    status: doc.value.status,
    acknowledgedOn: doc.value.acknowledged_on,
    isPrivacyOfficer: isPrivacyOfficer.value,
    isRequester: isRequester.value,
  }),
)
const breadcrumbs = computed(() => [
  { label: __('Erasure Requests'), route: { name: 'Erasure Requests' } },
  { label: props.name },
])

const reload = () => {
  request.reload()
  preview.reload()
}

async function run(method, params, message) {
  try {
    await call(method, { ...params })
    toast.success(message)
  } catch (e) {
    toast.error(serverMessage(e, __('The action failed')))
  }
  reload()
}

const act = (method, message) =>
  run(`crm.api.erasure.${method}`, { name: props.name }, message)

async function retry() {
  await act('retry_execution', __('Retrying'))
  // Hide the old error now; polling restarts and the next load shows a new one.
  if (request.data?.[0]) request.data[0].last_error = ''
}

const saveAcknowledged = (value) =>
  run(
    'frappe.client.set_value',
    {
      doctype: 'CRM Erasure Request',
      name: props.name,
      fieldname: 'acknowledged_on',
      value,
    },
    __('Acknowledgement saved'),
  )
</script>
