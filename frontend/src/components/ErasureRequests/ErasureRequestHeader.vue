<template>
  <div class="flex flex-col gap-3 rounded-lg border p-4">
    <div class="flex flex-wrap items-center gap-3">
      <h2 class="text-xl-semibold text-ink-gray-9">{{ request.name }}</h2>
      <Badge
        :label="__(request.status)"
        :theme="statusTheme(request.status)"
        variant="subtle"
      />
      <span
        v-if="request.status !== 'Closed'"
        class="text-p-base-medium"
        :class="
          daysLeftTone(request.days_left) === 'red'
            ? 'text-ink-red-4'
            : 'text-ink-gray-7'
        "
      >
        {{ daysLeftLabel(request.days_left) }}
      </span>
    </div>
    <p v-if="request.status === 'On Hold'" class="text-p-sm text-ink-gray-6">
      {{
        __(
          'An open deal still lists the person, so the request cannot be approved yet. The deal owners were told to remove the person or close the deal.',
        )
      }}
    </p>
    <div class="grid grid-cols-1 gap-3 text-sm sm:grid-cols-3">
      <div>
        <div class="text-ink-gray-5">{{ __('Acknowledge by') }}</div>
        <div class="text-ink-gray-8">
          {{ formatDate(request.acknowledge_by, '', true) || '—' }}
        </div>
        <div class="mt-1 flex items-center gap-2 text-ink-gray-6">
          <template v-if="request.acknowledgment_sent">
            {{
              __('Acknowledged on {0}', [
                formatDate(request.acknowledged_on, '', true),
              ])
            }}
          </template>
          <template v-else>
            {{ __('Not acknowledged yet') }}
            <Button
              v-if="request.can?.mark_acknowledged"
              size="sm"
              :label="__('Mark acknowledged')"
              :loading="saving"
              @click="confirmAcknowledged"
            />
          </template>
        </div>
      </div>
      <div>
        <div class="text-ink-gray-5">{{ __('Respond by') }}</div>
        <div class="text-ink-gray-8">
          {{ formatDate(request.respond_by, '', true) || '—' }}
        </div>
      </div>
      <div>
        <div class="text-ink-gray-5">{{ __('Logged by') }}</div>
        <div class="text-ink-gray-8">
          {{ getUser(request.logged_by).full_name }}
        </div>
      </div>
    </div>
    <div
      v-if="request.outcome || request.denial_reason"
      class="flex flex-col gap-1 border-t pt-3 text-sm text-ink-gray-7"
    >
      <div v-if="request.outcome">
        {{ __('Outcome: {0}', [__(request.outcome)]) }}
        <template v-if="request.date_answered">
          ·
          {{
            __('answered on {0}', [formatDate(request.date_answered, '', true)])
          }}
        </template>
      </div>
      <div v-if="request.denial_reason">
        {{ __('Reason: {0}', [request.denial_reason]) }}
      </div>
      <div v-if="request.purge_after" class="text-ink-gray-5">
        {{
          __('Only this log entry is kept, until {0}', [
            formatDate(request.purge_after, '', true),
          ])
        }}
      </div>
    </div>
  </div>
</template>

<script setup>
import { runAction } from '@/components/ErasureRequests/erasureApi'
import { usersStore } from '@/stores/users'
import { formatDate } from '@/utils'
import { createDialog } from '@/utils/dialogs'
import {
  daysLeftLabel,
  daysLeftTone,
  statusTheme,
} from '@/utils/erasureRequestDisplay'
import { Badge } from 'frappe-ui'
import { ref } from 'vue'

const props = defineProps({
  request: { type: Object, required: true },
})
const emit = defineEmits(['updated'])

const { getUser } = usersStore()
const saving = ref(false)

// Recording it is final (the date cannot be taken back), so ask first.
function confirmAcknowledged() {
  createDialog({
    title: __('Mark as acknowledged?'),
    message: __(
      'This records today as the day the requester was acknowledged. It cannot be undone.',
    ),
    actions: [
      {
        label: __('Mark acknowledged'),
        variant: 'solid',
        onClick: async ({ close }) => {
          close()
          saving.value = true
          const result = await runAction('review.mark_acknowledged', {
            name: props.request.name,
          })
          saving.value = false
          if (result) emit('updated', result)
        },
      },
    ],
  })
}
</script>
