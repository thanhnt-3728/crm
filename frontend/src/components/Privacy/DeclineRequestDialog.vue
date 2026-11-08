<template>
  <Dialog v-model:open="open" :title="__('Decline {0}', [requestName])">
    <template #default>
      <div class="flex flex-col gap-3">
        <p class="text-p-base text-ink-gray-6">
          {{
            __(
              'Nothing is erased. Give the reason; it is kept on the request and used if you close it as denied.',
            )
          }}
        </p>
        <FormControl
          v-model="reason"
          type="textarea"
          :label="__('Reason')"
          :rows="4"
        />
        <ErrorMessage :message="error" />
      </div>
    </template>
    <template #actions>
      <div class="flex justify-end gap-2">
        <Button variant="subtle" :label="__('Cancel')" @click="open = false" />
        <Button
          variant="solid"
          theme="red"
          :label="__('Decline request')"
          :loading="loading"
          :disabled="!reason.trim()"
          @click="decline"
        />
      </div>
    </template>
  </Dialog>
</template>

<script setup>
import { call } from 'frappe-ui'
import { ref, watch } from 'vue'

const props = defineProps({
  requestName: { type: String, required: true },
})
const emit = defineEmits(['done'])

const open = defineModel({ type: Boolean, default: false })
const reason = ref('')
const error = ref('')
const loading = ref(false)

watch(open, (value) => {
  if (value) {
    reason.value = ''
    error.value = ''
  }
})

async function decline() {
  loading.value = true
  error.value = ''
  try {
    const result = await call('crm.privacy.api.decline_request', {
      name: props.requestName,
      reason: reason.value,
    })
    open.value = false
    emit('done', result)
  } catch (e) {
    error.value = e?.messages?.[0] || e?.message || __('Could not decline')
  } finally {
    loading.value = false
  }
}
</script>
