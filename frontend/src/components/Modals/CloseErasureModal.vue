<template>
  <Dialog
    v-model:open="show"
    :title="__('Close request {0}', [request.name])"
    @close="close"
  >
    <template #default>
      <div class="-mt-3 mb-4 text-p-base text-ink-gray-7">
        {{
          __(
            "Closing wipes the requester's details and the checklist text. Only a log entry stays, for 24 months.",
          )
        }}
      </div>
      <div class="flex flex-col gap-4">
        <FormControl
          v-model="answeredOn"
          type="date"
          :label="__('Date answered')"
          required
        />
        <FormControl
          v-model="outcome"
          type="select"
          :label="__('Outcome')"
          :options="outcomeOptions"
          :disabled="declined"
          required
        />
        <FormControl
          v-if="outcome === 'Denied'"
          v-model="denialReason"
          type="textarea"
          :label="__('Denial reason')"
          :rows="3"
          required
        />
        <div v-if="openItems" class="text-sm text-ink-amber-7">
          {{
            __(
              'Every checklist item must be ticked before the request can be closed.',
            )
          }}
        </div>
      </div>
    </template>
    <template #actions>
      <div class="flex items-center justify-between gap-2">
        <div><ErrorMessage :message="error" /></div>
        <div class="flex gap-2">
          <Button :label="__('Cancel')" @click="close" />
          <Button
            variant="solid"
            :label="__('Close request')"
            :disabled="!canClose"
            :loading="saving"
            @click="closeRequest"
          />
        </div>
      </div>
    </template>
  </Dialog>
</template>

<script setup>
import { errorText } from '@/utils/erasureRequest'
import { call, dayjs, Dialog, toast } from 'frappe-ui'
import { computed, ref, watch } from 'vue'

const props = defineProps({
  // the request, as the page loaded it
  request: { type: Object, required: true },
})

// `refresh` fires on success and on failure, since either may have changed it.
const emit = defineEmits(['refresh'])
const show = defineModel({ type: Boolean })

const answeredOn = ref('')
const outcome = ref('')
const denialReason = ref('')
const error = ref('')
const saving = ref(false)

// A declined request was not carried out, so it can only be Denied.
const declined = computed(() => props.request.status === 'Declined')
const openItems = computed(() =>
  (props.request.checklist || []).some((row) => !row.done),
)
const outcomeOptions = computed(() =>
  [
    { label: __('Completed'), value: 'Completed' },
    { label: __('Partly completed'), value: 'Partly completed' },
    { label: __('Denied'), value: 'Denied' },
  ].filter((option) => !declined.value || option.value === 'Denied'),
)

const canClose = computed(
  () =>
    Boolean(answeredOn.value) &&
    Boolean(outcome.value) &&
    (outcome.value !== 'Denied' || Boolean(denialReason.value.trim())) &&
    !saving.value,
)

watch(show, (open) => {
  if (!open) return
  answeredOn.value = dayjs().format('YYYY-MM-DD')
  outcome.value = declined.value ? 'Denied' : ''
  denialReason.value = props.request.denial_reason || ''
  error.value = ''
})

function close() {
  show.value = false
}

async function closeRequest() {
  if (!canClose.value) return
  saving.value = true
  error.value = ''
  try {
    await call('crm.api.erasure.close', {
      name: props.request.name,
      answered_on: answeredOn.value,
      outcome: outcome.value,
      denial_reason:
        outcome.value === 'Denied' ? denialReason.value.trim() : '',
    })
    toast.success(__('Request closed'))
    emit('refresh')
    close()
  } catch (e) {
    error.value = errorText(e)
    emit('refresh')
  } finally {
    saving.value = false
  }
}
</script>
