<template>
  <Button
    :label="__('Request erasure')"
    iconLeft="lucide-shield-off"
    :loading="loading"
    @click="logRequest"
  />
</template>

<script setup>
import { Button, call, toast } from 'frappe-ui'
import { ref } from 'vue'
import { useRouter } from 'vue-router'

const props = defineProps({
  doctype: {
    type: String,
    required: true,
    validator: (value) => ['CRM Lead', 'CRM Deal', 'Contact'].includes(value),
  },
  docname: { type: String, required: true },
})

const router = useRouter()
const loading = ref(false)

async function logRequest() {
  loading.value = true
  try {
    const requestId = await call('crm.privacy.api.log_request', {
      source_doctype: props.doctype,
      source_name: props.docname,
    })
    router.push({ name: 'Erasure Request', params: { requestId } })
  } catch (error) {
    toast.error(
      error?.messages?.[0] ||
        error?.message ||
        __('Could not log the erasure request'),
    )
  } finally {
    loading.value = false
  }
}
</script>
