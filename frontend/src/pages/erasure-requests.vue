<template>
  <LayoutHeader>
    <template #left-header>
      <Breadcrumbs
        :items="[
          {
            label: __('Erasure Requests'),
            route: { name: 'Erasure Requests' },
          },
        ]"
      />
    </template>
  </LayoutHeader>
  <div class="h-full overflow-auto p-5">
    <ErrorMessage
      v-if="requests.error"
      :message="
        serverMessage(requests.error, __('Could not load erasure requests'))
      "
    />
    <div v-else-if="requests.loading && !rows.length" class="text-ink-gray-5">
      {{ __('Loading...') }}
    </div>
    <div v-else-if="!rows.length" class="text-ink-gray-5">
      {{ __('No erasure requests yet. Log one from a lead, deal or contact.') }}
    </div>
    <table v-else class="w-full text-left text-p-sm">
      <thead class="text-ink-gray-5">
        <tr>
          <th class="py-2 pr-4 font-medium">{{ __('Request') }}</th>
          <th class="py-2 pr-4 font-medium">{{ __('Person') }}</th>
          <th class="py-2 pr-4 font-medium">{{ __('Status') }}</th>
          <th class="py-2 pr-4 font-medium">{{ __('Received on') }}</th>
          <th class="py-2 pr-4 font-medium">{{ __('Acknowledge by') }}</th>
          <th class="py-2 pr-4 font-medium">{{ __('Respond by') }}</th>
        </tr>
      </thead>
      <tbody>
        <tr
          v-for="row in rows"
          :key="row.name"
          class="border-t border-outline-gray-1 hover:bg-surface-gray-2"
        >
          <td class="py-2 pr-4">
            <router-link
              class="text-ink-gray-8 underline"
              :to="{ name: 'Erasure Request', params: { name: row.name } }"
              >{{ row.name }}</router-link
            >
          </td>
          <td class="py-2 pr-4">{{ row.subject_name }}</td>
          <td class="py-2 pr-4">{{ __(row.status) }}</td>
          <td class="py-2 pr-4">{{ displayDate(row.received_on) }}</td>
          <td class="py-2 pr-4" :class="deadlineClasses[row.highlights.ack]">
            {{ displayDate(row.ack_due) }}
          </td>
          <td
            class="py-2 pr-4"
            :class="deadlineClasses[row.highlights.response]"
          >
            {{ displayDate(row.response_due) }}
          </td>
        </tr>
      </tbody>
    </table>
    <Button
      v-if="canLoadMore"
      class="mt-4"
      :label="__('Load more')"
      :loading="requests.loading"
      @click="loadMore"
    />
  </div>
</template>

<script setup>
import { Breadcrumbs, Button, ErrorMessage, createResource } from 'frappe-ui'
import { computed, ref } from 'vue'
import LayoutHeader from '@/components/LayoutHeader.vue'
import { displayDate } from '@/composables/erasure-display-date'
import {
  deadlineClasses,
  requestHighlights,
  todayString,
} from '@/utils/erasure-deadlines'
import { serverMessage } from '@/utils/erasure-matches'

const PAGE_SIZE = 50
const limit = ref(PAGE_SIZE)

const requests = createResource({
  url: 'frappe.client.get_list',
  makeParams: () => ({
    doctype: 'CRM Erasure Request',
    fields: [
      'name',
      'subject_name',
      'status',
      'received_on',
      'ack_due',
      'response_due',
      'acknowledged_on',
    ],
    order_by: 'response_due asc',
    limit_page_length: limit.value,
  }),
  auto: true,
})

const rows = computed(() => {
  const today = todayString()
  return (requests.data || []).map((row) => ({
    ...row,
    highlights: requestHighlights(row, today),
  }))
})
// A full page means there may be more.
const canLoadMore = computed(() => rows.value.length >= limit.value)

function loadMore() {
  limit.value += PAGE_SIZE
  requests.fetch()
}
</script>
