<template>
  <LayoutHeader>
    <template #left-header>
      <Breadcrumbs :items="[{ label: __('Erasure requests') }]" />
    </template>
    <template #right-header>
      <Button
        variant="solid"
        iconLeft="lucide-plus"
        :label="__('New request')"
        @click="showNew = true"
      />
    </template>
  </LayoutHeader>
  <div class="flex-1 overflow-y-auto">
    <div
      v-if="requests.loading && !requests.data"
      class="flex justify-center p-10"
    >
      <LoadingIndicator class="size-6" />
    </div>
    <div v-else-if="requests.error" class="p-5">
      <ErrorMessage :message="errorText(requests.error)" />
    </div>
    <EmptyState
      v-else-if="!requests.data?.length"
      :title="__('No erasure requests')"
      :description="
        __('Requests you log appear here, with the days left to answer them.')
      "
      :icon="ShieldIcon"
    />
    <div v-else class="px-5 py-3 text-base">
      <div
        class="grid grid-cols-5 gap-3 border-b px-3 py-2 text-sm text-ink-gray-5"
      >
        <div>{{ __('Request') }}</div>
        <div>{{ __('Status') }}</div>
        <div>{{ __('Days left') }}</div>
        <div>{{ __('Acknowledge by') }}</div>
        <div>{{ __('Respond by') }}</div>
      </div>
      <component
        :is="isOpenable(row) ? 'RouterLink' : 'div'"
        v-for="row in requests.data"
        :key="row.name"
        v-bind="isOpenable(row) ? { to: detailRoute(row) } : {}"
        class="grid grid-cols-5 items-center gap-3 border-b px-3 py-2.5 text-ink-gray-8"
        :class="isOpenable(row) ? 'hover:bg-surface-gray-2' : 'cursor-default'"
        :title="isOpenable(row) ? '' : __('Submitted to Compliance')"
      >
        <div class="font-medium">{{ row.name }}</div>
        <div>
          <Badge
            :label="__(row.status)"
            :theme="statusTheme(row.status)"
            variant="subtle"
          />
        </div>
        <div
          :class="
            daysTone(row) === 'red' ? 'text-ink-red-4' : 'text-ink-gray-7'
          "
        >
          {{ row.status === 'Closed' ? '—' : daysLeftLabel(row.days_left) }}
        </div>
        <div>{{ formatDate(row.acknowledge_by, '', true) || '—' }}</div>
        <div>{{ formatDate(row.respond_by, '', true) || '—' }}</div>
      </component>
    </div>
  </div>
  <NewErasureRequestDialog v-model="showNew" />
  <InboundMailDialog v-model="showMail" :mail-name="mailName" />
</template>

<script setup>
import LayoutHeader from '@/components/LayoutHeader.vue'
import EmptyState from '@/components/ListViews/EmptyState.vue'
import InboundMailDialog from '@/components/ErasureRequests/InboundMailDialog.vue'
import NewErasureRequestDialog from '@/components/ErasureRequests/NewErasureRequestDialog.vue'
import ShieldIcon from '~icons/lucide/shield-check'
import { formatDate } from '@/utils'
import {
  daysLeftLabel,
  daysLeftTone,
  errorText,
  statusTheme,
} from '@/utils/erasureRequestDisplay'
import {
  Badge,
  Breadcrumbs,
  ErrorMessage,
  LoadingIndicator,
  createResource,
  usePageMeta,
} from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import { useRoute } from 'vue-router'

const route = useRoute()
const showNew = ref(false)
const showMail = ref(false)
const mailName = computed(() => route.query.mail || '')

usePageMeta(() => ({ title: __('Erasure requests') }))

const requests = createResource({
  url: 'crm.api.erasure_requests.list_requests',
  auto: true,
})

// A notice about an inbound email opens it here (Compliance only; the server decides).
watch(mailName, (name) => (showMail.value = Boolean(name)), { immediate: true })

// A request the user submitted comes back trimmed to status and dates: no detail page.
const isOpenable = (row) => 'logged_by' in row
const detailRoute = (row) => ({
  name: 'ErasureRequest',
  params: { requestId: row.name },
})
const daysTone = (row) =>
  row.status === 'Closed' ? 'gray' : daysLeftTone(row.days_left)
</script>
