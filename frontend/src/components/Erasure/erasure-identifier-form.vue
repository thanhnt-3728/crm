<template>
  <div class="flex flex-col gap-3">
    <ExistingDraftNotice
      :source-doctype="sourceDoctype"
      :source-docname="sourceDocname"
      :active="active"
      @open="emit('open-draft')"
    />
    <FormControl
      v-model="subject"
      type="text"
      :label="__('Name of the person')"
      required
    />
    <FormControl
      v-model="receivedOn"
      type="date"
      :label="__('Request received on')"
      :max="maxDate"
      required
    />
    <FormControl
      v-model="emails"
      type="textarea"
      :rows="3"
      :label="__('Email addresses (one per line)')"
    />
    <FormControl
      v-model="phones"
      type="textarea"
      :rows="3"
      :label="__('Phone numbers (one per line)')"
    />
  </div>
</template>

<script setup>
import { FormControl } from 'frappe-ui'
import ExistingDraftNotice from '@/components/Erasure/existing-draft-notice.vue'

defineProps({
  sourceDoctype: { type: String, required: true },
  sourceDocname: { type: String, required: true },
  active: { type: Boolean, default: false },
  maxDate: { type: String, default: '' },
})
const emit = defineEmits(['open-draft'])
const subject = defineModel('subject', { type: String })
const receivedOn = defineModel('receivedOn', { type: String })
const emails = defineModel('emails', { type: String })
const phones = defineModel('phones', { type: String })
</script>
