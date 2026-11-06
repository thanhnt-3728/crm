<template>
  <Dialog v-model:open="show" :title="__('Reject erasure request')">
    <template #default>
      <FormControl
        v-model="reason"
        type="textarea"
        :rows="4"
        :label="__('Reason (required)')"
      />
    </template>
    <template #actions>
      <div class="flex justify-end gap-2">
        <Button :label="__('Cancel')" @click="show = false" />
        <Button
          variant="solid"
          theme="red"
          :label="__('Reject')"
          :disabled="!reason.trim()"
          :loading="busy"
          @click="reject"
        />
      </div>
    </template>
  </Dialog>
</template>

<script setup>
import { Dialog, FormControl, Button, call, toast } from 'frappe-ui'
import { ref, watch } from 'vue'
import { serverMessage } from '@/utils/erasure-matches'

const props = defineProps({
  requestName: { type: String, required: true },
})
const emit = defineEmits(['rejected'])
const show = defineModel({ type: Boolean })

const reason = ref('')
const busy = ref(false)

watch(show, (open) => {
  if (open) {
    reason.value = ''
  }
})

async function reject() {
  busy.value = true
  try {
    await call('crm.api.erasure.reject', {
      name: props.requestName,
      reason: reason.value.trim(),
    })
    toast.success(__('Request rejected'))
    show.value = false
    emit('rejected')
  } catch (e) {
    toast.error(serverMessage(e, __('Could not reject the request')))
  } finally {
    busy.value = false
  }
}
</script>
