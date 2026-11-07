<template>
  <Dialog v-model:open="show" :title="__('Close {0}', [request.name])">
    <template #default>
      <div class="flex flex-col gap-3">
        <Alert
          theme="amber"
          :title="__('Closing wipes the requester details')"
          :description="
            __(
              'Names, emails, phones, the message, matches and the checklist are erased. Only a log entry (dates, channel, outcome and reason) stays for 24 months. Send the outcome email first: closing needs the requester email to reply.',
            )
          "
        />
        <div>
          <Button
            variant="ghost"
            iconLeft="lucide-mail"
            :label="__('Use Erasure outcome template')"
            @click="emit('compose')"
          />
        </div>
        <ErrorMessage v-if="hasOpenItems" :message="blocked" />
        <FormControl
          v-model="form.date"
          type="date"
          :label="__('Date answered')"
          required
        />
        <FormControl
          v-model="form.outcome"
          type="select"
          :label="__('Outcome')"
          :options="outcomes"
          required
        />
        <FormControl
          v-if="needsReason"
          v-model="form.reason"
          type="textarea"
          :rows="3"
          :label="__('Reason')"
          :placeholder="request.denial_reason || ''"
          required
        />
      </div>
    </template>
    <template #actions>
      <div class="flex justify-end gap-2">
        <Button :label="__('Cancel')" @click="show = false" />
        <Button
          variant="solid"
          :label="__('Close request')"
          :loading="saving"
          :disabled="Boolean(blocked)"
          @click="close"
        />
      </div>
    </template>
  </Dialog>
</template>

<script setup>
import { runAction } from '@/components/ErasureRequests/erasureApi'
import {
  closeFormError,
  closeOutcomeOptions,
} from '@/utils/erasureRequestDisplay'
import { Alert, Dialog, ErrorMessage, FormControl, toast } from 'frappe-ui'
import { computed, reactive, ref, watch } from 'vue'

const props = defineProps({
  request: { type: Object, required: true },
})
const emit = defineEmits(['updated', 'compose'])

const show = defineModel({ type: Boolean })
const form = reactive({ date: '', outcome: '', reason: '' })
const saving = ref(false)

const outcomes = computed(() => [
  { label: '', value: '' },
  ...closeOutcomeOptions(props.request.status).map((value) => ({
    label: __(value),
    value,
  })),
])
const needsReason = computed(() =>
  ['Partly completed', 'Denied'].includes(form.outcome),
)

// Close stays disabled until the form is complete; open checklist items are the reason worth showing.
const blocked = computed(() => closeFormError(form, props.request))
const hasOpenItems = computed(() =>
  props.request.checklist?.some((item) => !item.done),
)

watch(show, () => {
  form.date = form.reason = ''
  form.outcome = props.request.status === 'Declined' ? 'Denied' : ''
})

async function close() {
  saving.value = true
  const result = await runAction('review.close_request', {
    name: props.request.name,
    date_answered: form.date,
    outcome: form.outcome,
    denial_reason: form.reason.trim() || null,
  })
  saving.value = false
  if (!result) return
  show.value = false
  toast.success(__('Request closed'))
  emit('updated', result)
}
</script>
