<template>
  <LayoutHeader>
    <template #left-header>
      <Breadcrumbs
        :items="[
          {
            label: __('Privacy requests'),
            route: { name: 'ErasureRequests' },
          },
        ]"
      />
    </template>
    <template #right-header>
      <Button
        v-if="LogErasureRequestModal"
        variant="solid"
        :label="__('Log request')"
        iconLeft="lucide-plus"
        @click="showLogModal = true"
      />
    </template>
  </LayoutHeader>

  <div class="flex items-center justify-between gap-3 px-3 py-2 sm:px-5">
    <div class="text-sm text-ink-gray-5">
      {{ __('Soonest due first') }}
    </div>
    <FormControl
      v-model="showClosed"
      type="checkbox"
      :label="__('Show closed')"
    />
  </div>

  <div class="flex-1 overflow-y-auto px-3 pb-3 sm:px-5 sm:pb-5">
    <div v-if="requests.error" class="py-8 text-center text-ink-red-4">
      <ErrorMessage :message="errorText(requests.error)" />
    </div>
    <div
      v-else-if="requests.loading && !rows.length"
      class="py-8 text-center text-ink-gray-5"
    >
      {{ __('Loading...') }}
    </div>
    <div
      v-else-if="!rows.length"
      class="flex flex-col items-center gap-2 py-16 text-ink-gray-5"
    >
      <LucideShieldCheck class="size-12 text-ink-gray-3" />
      <div class="text-lg-medium text-ink-gray-6">
        {{ __('No privacy requests') }}
      </div>
    </div>
    <table v-else class="w-full min-w-[720px] text-base">
      <thead>
        <tr class="border-b text-left text-sm text-ink-gray-5">
          <th class="py-2 pr-3 font-normal">{{ __('Request') }}</th>
          <th class="py-2 pr-3 font-normal">{{ __('Status') }}</th>
          <th class="py-2 pr-3 font-normal">{{ __('Received') }}</th>
          <th class="py-2 pr-3 font-normal">{{ __('Acknowledge by') }}</th>
          <th class="py-2 pr-3 font-normal">{{ __('Respond by') }}</th>
          <th class="py-2 font-normal">{{ __('Days left') }}</th>
        </tr>
      </thead>
      <tbody>
        <tr
          v-for="row in rows"
          :key="row.name"
          class="cursor-pointer border-b text-ink-gray-8 hover:bg-surface-gray-2"
          @click="openRequest(row.name)"
        >
          <td class="py-3 pr-3 font-medium">
            <router-link
              :to="{ name: 'ErasureRequest', params: { requestId: row.name } }"
              class="hover:underline"
              @click.stop
            >
              {{ row.name }}
            </router-link>
          </td>
          <td class="py-3 pr-3">
            <Badge :label="__(row.status)" :theme="statusTheme(row.status)" />
          </td>
          <td class="py-3 pr-3">{{ date(row.received_on) }}</td>
          <td class="py-3 pr-3">
            {{ date(row.acknowledge_by) }}
            <span
              v-if="row.acknowledgment_sent"
              class="ml-1 text-ink-green-3"
              :title="__('Acknowledgment sent')"
            >
              &#10003;
            </span>
          </td>
          <td class="py-3 pr-3">{{ date(row.respond_by) }}</td>
          <td class="py-3">
            <Badge
              v-if="row.status !== 'Closed'"
              :label="daysLeftLabel(row.days_left)"
              :theme="urgencyTheme(row.days_left)"
            />
          </td>
        </tr>
      </tbody>
    </table>
  </div>

  <component
    :is="LogErasureRequestModal"
    v-if="LogErasureRequestModal"
    v-model="showLogModal"
  />
</template>

<script setup>
import LayoutHeader from '@/components/LayoutHeader.vue'
import LucideShieldCheck from '~icons/lucide/shield-check'
import { formatDate } from '@/utils'
import {
  daysLeftLabel,
  errorText,
  sortByDaysLeft,
  statusTheme,
  urgencyTheme,
} from '@/utils/erasureRequest'
import { Breadcrumbs, createResource } from 'frappe-ui'
import { computed, defineAsyncComponent, markRaw, ref, watch } from 'vue'
import { useRouter } from 'vue-router'

const router = useRouter()
const showClosed = ref(false)
const showLogModal = ref(false)

// The log-request modal ships with the record actions. The button only shows
// once that file exists, so this page doesn't depend on it to build.
const logModals = import.meta.glob(
  '../components/Modals/LogErasureRequestModal.vue',
)
const logModalLoader = Object.values(logModals)[0]
const LogErasureRequestModal = logModalLoader
  ? markRaw(defineAsyncComponent(logModalLoader))
  : null

const requests = createResource({
  url: 'crm.api.erasure.list_requests',
  makeParams: () => ({ include_closed: showClosed.value ? 1 : 0 }),
  auto: true,
})

watch(showClosed, () => requests.reload())
// A request logged from the modal shows up when the list is next opened.
watch(showLogModal, (open) => {
  if (!open) requests.reload()
})

const rows = computed(() => sortByDaysLeft(requests.data || []))

function date(value) {
  return value ? formatDate(value, 'MMM D, YYYY') : ''
}

function openRequest(name) {
  router.push({ name: 'ErasureRequest', params: { requestId: name } })
}
</script>
