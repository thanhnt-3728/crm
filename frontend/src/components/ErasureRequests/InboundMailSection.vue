<template>
  <section
    v-if="mails.length"
    class="flex flex-col gap-3 rounded-lg border p-4"
  >
    <div>
      <h3 class="text-lg-medium text-ink-gray-9">{{ __('Inbound email') }}</h3>
      <p class="text-p-sm text-ink-gray-6">
        {{
          __(
            'Email that arrived from an address on this request while it was open. It is never turned into a lead.',
          )
        }}
      </p>
    </div>
    <div class="divide-y text-base">
      <button
        v-for="mail in mails"
        :key="mail.name"
        class="flex w-full items-center gap-3 px-2 py-2 text-left hover:bg-surface-gray-2"
        @click="openMail(mail.name)"
      >
        <div class="min-w-0 flex-1">
          <div class="truncate text-ink-gray-8">
            {{ mail.subject || __('(no subject)') }}
          </div>
          <div class="truncate text-p-sm text-ink-gray-5">
            {{ mail.sender }}
          </div>
        </div>
        <div class="text-p-sm text-ink-gray-5">
          {{ formatDate(mail.communication_date) }}
        </div>
      </button>
    </div>
  </section>
  <InboundMailDialog v-model="showMail" :mail-name="mailName" />
</template>

<script setup>
import InboundMailDialog from '@/components/ErasureRequests/InboundMailDialog.vue'
import { erasureCall } from '@/components/ErasureRequests/erasureApi'
import { formatDate } from '@/utils'
import { ref, watch } from 'vue'

const props = defineProps({
  request: { type: Object, required: true },
})

const mails = ref([])
const showMail = ref(false)
const mailName = ref('')

// Compliance only (the page mounts this section for them): a failure just leaves the section out.
watch(
  () => props.request.modified,
  async () => {
    try {
      mails.value = await erasureCall('inbound.list_request_communications', {
        name: props.request.name,
      })
    } catch {
      mails.value = []
    }
  },
  { immediate: true },
)

function openMail(name) {
  mailName.value = name
  showMail.value = true
}
</script>
