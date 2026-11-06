<template>
  <div
    v-if="holdDeals.length"
    class="mt-4 rounded bg-surface-amber-2 p-3 text-p-sm text-ink-amber-3"
  >
    {{ __('On hold: open deals linked to this person') }}
    <router-link
      v-for="deal in holdDeals"
      :key="deal"
      class="ml-2 underline"
      :to="{ name: 'Deal', params: { dealId: deal } }"
      >{{ deal }}</router-link
    >
  </div>
  <div v-if="request.rejection_reason" class="mt-4 text-p-sm">
    <span class="text-ink-gray-5">{{ __('Rejected:') }}</span>
    {{ request.rejection_reason }}
  </div>
  <div
    v-if="stalled && !request.last_error"
    class="mt-4 rounded bg-surface-red-2 p-3 text-p-sm text-ink-red-4"
  >
    {{ __('Execution has not finished. Retry.') }}
  </div>
  <div
    v-if="request.last_error && cleanupPending"
    class="mt-4 rounded bg-surface-gray-2 p-3 text-p-sm text-ink-gray-7"
  >
    {{
      __(
        'Erasure finished. Some files are still on disk; a System Manager must finish the file cleanup.',
      )
    }}
  </div>
  <div
    v-else-if="request.last_error"
    class="mt-4 rounded bg-surface-red-2 p-3 text-p-sm text-ink-red-4"
  >
    {{ __('Last error: {0}', [request.last_error]) }}
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  request: { type: Object, required: true },
  stalled: { type: Boolean, default: false },
})

// On a finished erasure, last_error only carries the pending disk-file hint
// (crm/erasure/post_commit.py pending_hint); it is not a failure.
const cleanupPending = computed(() =>
  ['Executed', 'Closed'].includes(props.request.status),
)

// hold_reason is a comma-separated list of deal names.
const holdDeals = computed(() =>
  (props.request.hold_reason || '')
    .split(',')
    .map((deal) => deal.trim())
    .filter(Boolean),
)
</script>
