<template>
  <div class="flex h-full flex-col overflow-hidden">
    <LayoutHeader>
      <template #left-header>
        <ViewBreadcrumbs routeName="Erasure Requests" />
      </template>
      <template #right-header>
        <Button
          variant="solid"
          iconLeft="lucide-plus"
          :label="__('New request')"
          :loading="creating"
          @click="newRequest"
        />
      </template>
    </LayoutHeader>

    <div
      v-if="requests.loading && !requests.data"
      class="flex flex-1 items-center justify-center"
    >
      <LoadingIndicator class="h-6 w-6 text-ink-gray-5" />
    </div>

    <div
      v-else-if="!requests.data?.length"
      class="flex flex-1 flex-col items-center justify-center gap-2 text-ink-gray-5"
    >
      <LucideShieldOff class="h-10 w-10" />
      <div class="text-lg-medium">{{ __('No erasure requests') }}</div>
      <div class="text-p-base">
        {{ __('Log a request to start the 45-day clock.') }}
      </div>
    </div>

    <div v-else class="flex-1 overflow-y-auto px-3 pb-5 sm:px-5">
      <div
        class="grid gap-3 border-b px-3 py-2 text-sm text-ink-gray-5"
        :style="{ gridTemplateColumns: columnsTemplate }"
      >
        <div v-for="column in columns" :key="column.key">
          {{ column.label }}
        </div>
      </div>
      <router-link
        v-for="row in requests.data"
        :key="row.name"
        :to="{ name: 'Erasure Request', params: { requestId: row.name } }"
        class="grid items-center gap-3 border-b px-3 py-2.5 text-base text-ink-gray-8 hover:bg-surface-gray-2"
        :style="{ gridTemplateColumns: columnsTemplate }"
      >
        <div class="truncate font-medium">{{ row.name }}</div>
        <div class="truncate">{{ row.requester_name || '' }}</div>
        <div>
          <Badge
            variant="subtle"
            size="md"
            :theme="statusTheme(row.status)"
            :label="__(row.status)"
          />
        </div>
        <div class="truncate">
          {{ formatDate(row.date_received, '', true) }}
        </div>
        <div class="truncate">
          {{ formatDate(row.acknowledge_by, '', true) }}
        </div>
        <div
          class="truncate"
          :class="row.days_left < 0 ? 'text-ink-red-4' : ''"
        >
          {{ daysLeftLabel(row.days_left) }}
        </div>
      </router-link>
    </div>
  </div>
</template>

<script setup>
import LayoutHeader from '@/components/LayoutHeader.vue'
import ViewBreadcrumbs from '@/components/ViewBreadcrumbs.vue'
import { daysLeftLabel, statusTheme } from '@/utils/erasureRequest'
import { formatDate } from '@/utils'
import {
  Badge,
  Button,
  LoadingIndicator,
  call,
  createResource,
  toast,
} from 'frappe-ui'
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import LucideShieldOff from '~icons/lucide/shield-off'

const router = useRouter()
const creating = ref(false)

const columns = [
  { key: 'name', label: __('Request') },
  { key: 'requester_name', label: __('Requester') },
  { key: 'status', label: __('Status') },
  { key: 'date_received', label: __('Received') },
  { key: 'acknowledge_by', label: __('Acknowledge by') },
  { key: 'days_left', label: __('Days left') },
]
const columnsTemplate = '1fr 1.6fr 1.2fr 1fr 1fr 1.4fr'

const requests = createResource({
  url: 'crm.privacy.api.get_requests',
  auto: true,
})

async function newRequest() {
  creating.value = true
  try {
    const name = await call('crm.privacy.api.log_request')
    router.push({ name: 'Erasure Request', params: { requestId: name } })
  } catch (error) {
    toast.error(error?.messages?.[0] || __('Could not log the request'))
  } finally {
    creating.value = false
  }
}
</script>
