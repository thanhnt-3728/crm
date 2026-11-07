<template>
  <section class="flex flex-col gap-3 rounded-lg border p-4">
    <div class="flex items-center justify-between">
      <h3 class="text-lg-medium text-ink-gray-9">
        {{ __('Requester details') }}
      </h3>
      <Button
        v-if="editable && dirty"
        variant="solid"
        :label="__('Save')"
        :loading="saving"
        @click="save"
      />
    </div>
    <div class="grid grid-cols-2 gap-3">
      <FormControl
        v-model="form.channel"
        type="select"
        :label="__('How it arrived')"
        :options="channelOptions"
        :disabled="!editable"
      />
      <FormControl
        v-model="form.date_received"
        type="date"
        :label="__('Date received')"
        :disabled="!editable"
      />
    </div>
    <FormControl
      v-model="form.requester_names"
      type="text"
      :label="__('Name(s)')"
      :disabled="!editable"
    />
    <FormControl
      v-model="form.original_message"
      type="textarea"
      :rows="3"
      :label="__('Original message')"
      :disabled="!editable"
    />
    <div v-if="editable" class="grid grid-cols-2 gap-3">
      <FormControl
        v-model="addEmails"
        type="textarea"
        :rows="2"
        :label="__('Add email addresses')"
        :placeholder="__('One per line or separated by commas')"
      />
      <FormControl
        v-model="addPhones"
        type="textarea"
        :rows="2"
        :label="__('Add phone numbers')"
        :placeholder="__('One per line or separated by commas')"
      />
    </div>
  </section>
</template>

<script setup>
import { CHANNELS, runAction } from '@/components/ErasureRequests/erasureApi'
import { splitIdentifiers } from '@/utils/erasureRequestDisplay'
import { FormControl, toast } from 'frappe-ui'
import { computed, reactive, ref, watch } from 'vue'

const props = defineProps({
  request: { type: Object, required: true },
})
const emit = defineEmits(['updated'])

const FIELDS = [
  'channel',
  'date_received',
  'requester_names',
  'original_message',
]
const channelOptions = CHANNELS.map((value) => ({ label: __(value), value }))

// Locked while the erasure job runs, after the erasure and for a logger once submitted: the server's flag decides.
const editable = computed(() => Boolean(props.request.can?.edit))

const form = reactive({})
const addEmails = ref('')
const addPhones = ref('')
const saving = ref(false)

// Reset the form only when the saved request changed, so a refresh that changed nothing keeps what is being typed.
watch(
  () => props.request.modified,
  () => {
    FIELDS.forEach((field) => (form[field] = props.request[field] || ''))
    addEmails.value = addPhones.value = ''
  },
  { immediate: true },
)

const dirty = computed(
  () =>
    FIELDS.some(
      (field) => (form[field] || '') !== (props.request[field] || ''),
    ) ||
    splitIdentifiers(addEmails.value).length > 0 ||
    splitIdentifiers(addPhones.value).length > 0,
)

async function save() {
  const values = {}
  FIELDS.forEach((field) => {
    if ((form[field] || '') !== (props.request[field] || ''))
      values[field] = form[field] || null
  })
  const emails = splitIdentifiers(addEmails.value)
  const phones = splitIdentifiers(addPhones.value)
  if (emails.length) values.emails = emails
  if (phones.length) values.phones = phones
  saving.value = true
  const result = await runAction('requests.update_request', {
    name: props.request.name,
    values,
  })
  saving.value = false
  if (!result) return
  toast.success(__('Request updated'))
  emit('updated', result)
}
</script>
