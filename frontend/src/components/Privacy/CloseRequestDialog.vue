<template>
  <Dialog v-model:open="open" :title="__('Close {0}', [requestName])">
    <template #default>
      <div class="flex flex-col gap-3">
        <p class="text-p-base text-ink-gray-6">
          {{
            __(
              'Closing removes the identifiers, matches and free text left on this request. There is no undo.',
            )
          }}
        </p>
        <FormControl
          v-model="dateAnswered"
          type="date"
          :label="__('Date answered')"
        />
        <FormControl
          v-model="outcome"
          type="select"
          :label="__('Outcome')"
          :options="outcomeOptions"
          :disabled="declined"
        />
        <FormControl
          v-if="outcome === 'Denied'"
          v-model="denialReason"
          type="textarea"
          :label="__('Denial reason')"
          :placeholder="
            declined ? __('Leave blank to use the reason it was declined') : ''
          "
          :rows="3"
        />
        <ErrorMessage :message="error" />
      </div>
    </template>
    <template #actions>
      <div class="flex justify-end gap-2">
        <Button variant="subtle" :label="__('Cancel')" @click="open = false" />
        <Button
          variant="solid"
          :label="__('Close request')"
          :loading="loading"
          :disabled="!dateAnswered || !outcome"
          @click="close"
        />
      </div>
    </template>
  </Dialog>
</template>

<script setup>
import { OUTCOMES } from '@/utils/erasureRequest'
import { call } from 'frappe-ui'
import { computed, ref, watch } from 'vue'

const props = defineProps({
  requestName: { type: String, required: true },
  // A declined request may only be closed as Denied.
  declined: { type: Boolean, default: false },
})
const emit = defineEmits(['done'])

const open = defineModel({ type: Boolean, default: false })
const dateAnswered = ref('')
const outcome = ref('')
const denialReason = ref('')
const error = ref('')
const loading = ref(false)

const outcomeOptions = computed(() =>
  OUTCOMES.map((value) => ({ label: __(value), value })),
)

watch(open, (value) => {
  if (value) {
    dateAnswered.value = ''
    outcome.value = props.declined ? 'Denied' : ''
    denialReason.value = ''
    error.value = ''
  }
})

async function close() {
  loading.value = true
  error.value = ''
  try {
    const result = await call('crm.privacy.api.close_request', {
      name: props.requestName,
      date_answered: dateAnswered.value,
      outcome: outcome.value,
      denial_reason: outcome.value === 'Denied' ? denialReason.value : null,
    })
    open.value = false
    emit('done', result)
  } catch (e) {
    error.value = e?.messages?.[0] || e?.message || __('Could not close')
  } finally {
    loading.value = false
  }
}
</script>
