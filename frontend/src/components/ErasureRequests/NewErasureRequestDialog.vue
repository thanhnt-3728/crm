<template>
  <Dialog v-model:open="show" :title="__('Request erasure')" size="xl">
    <template #default>
      <div class="flex flex-col gap-4">
        <p class="text-p-sm text-ink-gray-6">
          {{
            source
              ? __(
                  'Log a privacy erasure request for the person on this record. Compliance reviews it before anything is erased.',
                )
              : __(
                  'Log a privacy erasure request for someone who may not be in the CRM under the address they wrote from.',
                )
          }}
        </p>
        <FormControl
          v-if="source?.contacts?.length > 1"
          v-model="contact"
          type="select"
          :label="__('Which contact is the requester?')"
          :options="[{ label: '', value: '' }, ...source.contacts]"
          required
        />
        <div class="grid grid-cols-2 gap-3">
          <FormControl
            v-model="channel"
            type="select"
            :label="__('How it arrived')"
            :options="channelOptions"
          />
          <FormControl
            v-model="dateReceived"
            type="date"
            :label="__('Date received')"
            :placeholder="__('Today')"
          />
        </div>
        <FormControl
          v-model="names"
          type="text"
          :label="__('Name(s)')"
          :placeholder="__('Name the requester gave')"
        />
        <FormControl
          v-model="emails"
          type="textarea"
          :rows="2"
          :label="__('Email addresses')"
          :placeholder="__('One per line or separated by commas')"
        />
        <FormControl
          v-model="phones"
          type="textarea"
          :rows="2"
          :label="__('Phone numbers')"
          :placeholder="__('One per line or separated by commas')"
        />
        <FormControl
          v-model="message"
          type="textarea"
          :rows="3"
          :label="__('Original message')"
        />
      </div>
    </template>
    <template #actions>
      <div class="flex justify-end gap-2">
        <Button :label="__('Cancel')" @click="show = false" />
        <Button
          variant="solid"
          :label="__('Create request')"
          :loading="saving"
          :disabled="!canCreate"
          @click="create"
        />
      </div>
    </template>
  </Dialog>
</template>

<script setup>
import { CHANNELS, runAction } from '@/components/ErasureRequests/erasureApi'
import { splitIdentifiers } from '@/utils/erasureRequestDisplay'
import { Dialog, FormControl, toast } from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'

const props = defineProps({
  // { doctype, name, contacts: [{ label, value }] } when started from a record
  source: { type: Object, default: null },
})

const show = defineModel({ type: Boolean })
const router = useRouter()

const channelOptions = CHANNELS.map((value) => ({ label: __(value), value }))
const channel = ref('Email')
const dateReceived = ref('')
const names = ref('')
const emails = ref('')
const phones = ref('')
const message = ref('')
const contact = ref('')
const saving = ref(false)

const needsContact = computed(() => props.source?.contacts?.length > 1)
const canCreate = computed(() => !needsContact.value || Boolean(contact.value))

// Nothing typed here is kept once the dialog closes (no storage).
watch(show, (open) => {
  if (open) return
  dateReceived.value = names.value = emails.value = ''
  phones.value = message.value = contact.value = ''
  channel.value = 'Email'
})

async function create() {
  saving.value = true
  const only =
    props.source?.contacts?.length === 1 ? props.source.contacts[0] : null
  const name = await runAction('requests.create_request', {
    source_doctype: props.source?.doctype || null,
    source_name: props.source?.name || null,
    contact: contact.value || only?.value || null,
    channel: channel.value,
    date_received: dateReceived.value || '',
    requester_names: names.value.trim() || null,
    emails: splitIdentifiers(emails.value),
    phones: splitIdentifiers(phones.value),
    original_message: message.value.trim() || null,
  })
  saving.value = false
  if (!name) return
  show.value = false
  toast.success(__('Request {0} logged', [name]))
  router.push({ name: 'ErasureRequest', params: { requestId: name } })
}
</script>
