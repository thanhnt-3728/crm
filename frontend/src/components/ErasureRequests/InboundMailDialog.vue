<!-- eslint-disable vue/no-v-html -->
<template>
  <Dialog
    v-model:open="show"
    :title="mail?.subject || __('Inbound email')"
    size="2xl"
  >
    <template #default>
      <div v-if="loading" class="flex justify-center p-6">
        <LoadingIndicator class="size-5" />
      </div>
      <ErrorMessage v-else-if="error" :message="error" />
      <div
        v-else-if="mail"
        class="flex flex-col gap-3 text-base text-ink-gray-8"
      >
        <div class="grid grid-cols-[5rem_1fr] gap-x-3 gap-y-1 text-sm">
          <span class="text-ink-gray-5">{{ __('From') }}</span>
          <span
            >{{ mail.sender_full_name || mail.sender }} &lt;{{
              mail.sender
            }}&gt;</span
          >
          <span class="text-ink-gray-5">{{ __('To') }}</span>
          <span>{{ mail.recipients }}</span>
          <template v-if="mail.cc">
            <span class="text-ink-gray-5">{{ __('CC') }}</span>
            <span>{{ mail.cc }}</span>
          </template>
          <span class="text-ink-gray-5">{{ __('Date') }}</span>
          <span>{{ formatDate(mail.communication_date) }}</span>
        </div>
        <div
          class="prose-sm max-h-96 max-w-none overflow-y-auto border-t pt-3"
          v-html="sanitizeHTML(mail.content)"
        />
      </div>
    </template>
  </Dialog>
</template>

<script setup>
import { erasureCall } from '@/components/ErasureRequests/erasureApi'
import { formatDate, sanitizeHTML } from '@/utils'
import { errorText } from '@/utils/erasureRequestDisplay'
import { Dialog, ErrorMessage, LoadingIndicator } from 'frappe-ui'
import { ref, watch } from 'vue'

const props = defineProps({
  mailName: { type: String, default: '' },
})

const show = defineModel({ type: Boolean })
const mail = ref(null)
const loading = ref(false)
const error = ref('')

// Compliance only: the endpoint refuses anyone else and any mail not tied to a request or a blocked sender.
watch(
  () => [show.value, props.mailName],
  async ([open, name]) => {
    if (!open || !name) return
    loading.value = true
    error.value = ''
    mail.value = null
    try {
      mail.value = await erasureCall('inbound.get_inbound_communication', {
        name,
      })
    } catch (e) {
      error.value = errorText(e)
    }
    loading.value = false
  },
  { immediate: true },
)
</script>
