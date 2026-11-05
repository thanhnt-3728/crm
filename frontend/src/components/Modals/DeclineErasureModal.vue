<template>
  <Dialog
    v-model:open="show"
    :title="__('Decline request {0}', [request])"
    @close="close"
  >
    <template #default>
      <div class="-mt-3 mb-4 text-p-base text-ink-gray-7">
        {{
          __(
            'Nothing is erased. The reason is kept with the request and goes into the reply.',
          )
        }}
      </div>
      <FormControl
        v-model="reason"
        type="textarea"
        :label="__('Reason')"
        :placeholder="__('For example: identity could not be verified')"
        :rows="4"
        required
      />
    </template>
    <template #actions>
      <div class="flex items-center justify-between gap-2">
        <div><ErrorMessage :message="error" /></div>
        <div class="flex gap-2">
          <Button :label="__('Cancel')" @click="close" />
          <Button
            variant="solid"
            theme="red"
            :label="__('Decline')"
            :disabled="!reason.trim()"
            :loading="saving"
            @click="decline"
          />
        </div>
      </div>
    </template>
  </Dialog>
</template>

<script setup>
import { errorText } from '@/utils/erasureRequest'
import { call, Dialog, toast } from 'frappe-ui'
import { ref, watch } from 'vue'

const props = defineProps({
  // the request number
  request: { type: String, required: true },
})

// `refresh` fires on success and on failure, since either may have changed it.
const emit = defineEmits(['refresh'])
const show = defineModel({ type: Boolean })

const reason = ref('')
const error = ref('')
const saving = ref(false)

watch(show, (open) => {
  if (!open) return
  reason.value = ''
  error.value = ''
})

function close() {
  show.value = false
}

async function decline() {
  if (!reason.value.trim()) return
  saving.value = true
  error.value = ''
  try {
    await call('crm.api.erasure.decline', {
      name: props.request,
      reason: reason.value.trim(),
    })
    toast.success(__('Request declined'))
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
