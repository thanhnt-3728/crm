<template>
  <Dialog v-model:open="show" :title="__('Decline {0}', [request.name])">
    <template #default>
      <div class="flex flex-col gap-3">
        <p class="text-p-sm text-ink-gray-6">
          {{
            __(
              'Nothing is erased. Write the reason, for example that the identity could not be verified or a legal exemption applies. It is kept in the log entry after the request closes.',
            )
          }}
        </p>
        <FormControl
          v-model="reason"
          type="textarea"
          :rows="4"
          :label="__('Reason')"
          required
        />
      </div>
    </template>
    <template #actions>
      <div class="flex justify-end gap-2">
        <Button :label="__('Cancel')" @click="show = false" />
        <Button
          variant="solid"
          theme="red"
          :label="__('Decline request')"
          :loading="saving"
          :disabled="!reason.trim()"
          @click="decline"
        />
      </div>
    </template>
  </Dialog>
</template>

<script setup>
import { runAction } from '@/components/ErasureRequests/erasureApi'
import { Dialog, FormControl, toast } from 'frappe-ui'
import { ref, watch } from 'vue'

const props = defineProps({
  request: { type: Object, required: true },
})
const emit = defineEmits(['updated'])

const show = defineModel({ type: Boolean })
const reason = ref('')
const saving = ref(false)

watch(show, () => (reason.value = ''))

async function decline() {
  saving.value = true
  const result = await runAction('review.decline_request', {
    name: props.request.name,
    reason: reason.value.trim(),
  })
  saving.value = false
  if (!result) return
  show.value = false
  toast.success(__('Request declined'))
  emit('updated', result)
}
</script>
