<template>
  <dl class="grid max-w-xl grid-cols-2 gap-y-2 text-p-sm">
    <dt class="text-ink-gray-5">{{ __('Received on') }}</dt>
    <dd>{{ displayDate(request.received_on) }}</dd>
    <dt class="text-ink-gray-5">{{ __('Acknowledge by') }}</dt>
    <dd :class="deadlineClasses[highlights.ack]">
      {{ displayDate(request.ack_due) }}
    </dd>
    <dt class="text-ink-gray-5">{{ __('Respond by') }}</dt>
    <dd :class="deadlineClasses[highlights.response]">
      {{ displayDate(request.response_due) }}
    </dd>
    <dt class="text-ink-gray-5">{{ __('Acknowledged on') }}</dt>
    <dd v-if="canAcknowledge" class="flex items-center gap-2">
      <FormControl v-model="ackDate" type="date" :max="todayString()" />
      <Button
        :label="__('Save')"
        :disabled="!ackDate"
        @click="emit('acknowledge', ackDate)"
      />
    </dd>
    <dd v-else>{{ displayDate(request.acknowledged_on) || '-' }}</dd>
  </dl>
</template>

<script setup>
import { Button, FormControl } from 'frappe-ui'
import { computed, ref } from 'vue'
import { displayDate } from '@/composables/erasure-display-date'
import {
  deadlineClasses,
  requestHighlights,
  todayString,
} from '@/utils/erasure-deadlines'

const props = defineProps({
  request: { type: Object, required: true },
  canAcknowledge: { type: Boolean, default: false },
})
const emit = defineEmits(['acknowledge'])

const ackDate = ref('')
const highlights = computed(() =>
  requestHighlights(props.request, todayString()),
)
</script>
