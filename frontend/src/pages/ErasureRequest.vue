<template>
  <LayoutHeader>
    <template #left-header>
      <Breadcrumbs
        :items="[
          { label: __('Erasure requests'), route: { name: 'ErasureRequests' } },
          {
            label: requestId,
            route: { name: 'ErasureRequest', params: { requestId } },
          },
        ]"
      />
    </template>
    <template #right-header>
      <ErasureRequestActions
        v-if="data?.can"
        :request="data"
        @updated="onUpdated"
      />
    </template>
  </LayoutHeader>
  <div class="flex-1 overflow-y-auto">
    <div
      v-if="request.loading && !data && !submitted"
      class="flex justify-center p-10"
    >
      <LoadingIndicator class="size-6" />
    </div>
    <div
      v-else-if="submitted"
      class="mx-auto flex max-w-3xl flex-col gap-3 p-5"
    >
      <Alert
        theme="green"
        :title="__('{0} was submitted to Compliance', [submitted.name])"
        :description="
          __(
            'It is {0}. Respond by {1}. Compliance takes it from here, so you can no longer open or edit it.',
            [__(submitted.status), formatDate(submitted.respond_by, '', true)],
          )
        "
      />
      <div>
        <Button
          :label="__('Back to erasure requests')"
          @click="router.push({ name: 'ErasureRequests' })"
        />
      </div>
    </div>
    <div
      v-else-if="request.error && !data"
      class="mx-auto flex max-w-3xl flex-col gap-3 p-5"
    >
      <ErrorMessage :message="errorText(request.error)" />
      <div>
        <Button
          :label="__('Back to erasure requests')"
          @click="router.push({ name: 'ErasureRequests' })"
        />
      </div>
    </div>
    <div v-else-if="data" class="mx-auto flex max-w-3xl flex-col gap-5 p-5">
      <Alert
        v-if="banner"
        :theme="banner.tone"
        :title="banner.title"
        :description="banner.text"
      />
      <ErasureRequestHeader :request="data" @updated="onUpdated" />
      <RequesterDetailsSection :request="data" @updated="onUpdated" />
      <IdentifiersSection :request="data" @updated="onUpdated" />
      <MatchesSection :request="data" @updated="onUpdated" />
      <ContractReferencesSection
        v-if="
          data.can.set_contract_references || data.contract_references?.length
        "
        :request="data"
        :editable="Boolean(data.can.set_contract_references)"
        @updated="onUpdated"
      />
      <ChecklistSection
        v-if="data.checklist?.length || data.can.manage_checklist"
        :request="data"
        @updated="onUpdated"
      />
      <InboundMailSection v-if="compliance" :request="data" />
    </div>
  </div>
</template>

<script setup>
import LayoutHeader from '@/components/LayoutHeader.vue'
import ChecklistSection from '@/components/ErasureRequests/ChecklistSection.vue'
import ContractReferencesSection from '@/components/ErasureRequests/ContractReferencesSection.vue'
import ErasureRequestActions from '@/components/ErasureRequests/ErasureRequestActions.vue'
import ErasureRequestHeader from '@/components/ErasureRequests/ErasureRequestHeader.vue'
import IdentifiersSection from '@/components/ErasureRequests/IdentifiersSection.vue'
import InboundMailSection from '@/components/ErasureRequests/InboundMailSection.vue'
import MatchesSection from '@/components/ErasureRequests/MatchesSection.vue'
import RequesterDetailsSection from '@/components/ErasureRequests/RequesterDetailsSection.vue'
import { formatDate } from '@/utils'
import {
  createFailureGate,
  errorText,
  isComplianceView,
  jobBanner,
} from '@/utils/erasureRequestDisplay'
import {
  Alert,
  Breadcrumbs,
  ErrorMessage,
  LoadingIndicator,
  createResource,
  toast,
  usePageMeta,
} from 'frappe-ui'
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useRouter } from 'vue-router'

const POLL_MS = 3000

const props = defineProps({
  requestId: { type: String, required: true },
})

const router = useRouter()
const submitted = ref(null)
const refreshFailures = createFailureGate()

usePageMeta(() => ({ title: props.requestId }))

const request = createResource({
  url: 'crm.api.erasure_requests.get_request',
  makeParams: () => ({ name: props.requestId }),
  auto: true,
  onSuccess: () => refreshFailures.reset(),
  // the first load shows its own error; a refresh that fails later (polling) says so once
  onError: (error) => {
    if (data.value && refreshFailures.shouldNotify()) {
      toast.error(errorText(error))
    }
  },
})

const data = computed(() => request.data)
const banner = computed(() => jobBanner(data.value))
const compliance = computed(() => isComplianceView(data.value?.can))

watch(
  () => props.requestId,
  () => {
    submitted.value = null
    request.reload()
  },
)

// A logger who submits gets only status and dates back and loses access: show that, not the form.
function onUpdated(result) {
  if (result?.can) request.setData(result)
  else submitted.value = result
}

// While the erasure job is Queued or Running, refresh every 3 seconds so the banner and the locked controls
// follow it. Polling stops when the job ends and when the page goes away.
let timer = null
const stopPolling = () => {
  clearInterval(timer)
  timer = null
}
watch(
  () => data.value?.erasure_job_status,
  (status) => {
    stopPolling()
    if (status === 'Queued' || status === 'Running') {
      timer = setInterval(() => request.reload(), POLL_MS)
    }
  },
  { immediate: true },
)
onBeforeUnmount(stopPolling)
</script>
