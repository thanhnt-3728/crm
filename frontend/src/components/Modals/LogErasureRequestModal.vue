<template>
  <Dialog v-model:open="show" :title="__('Log erasure request')" @close="close">
    <template #default>
      <div class="-mt-3 mb-4 text-p-base text-ink-gray-7">
        {{
          startDoctype
            ? __(
                'Record the request as it arrived. Compliance reviews it before anything is erased.',
              )
            : __(
                'Record a request that did not start from a lead or contact. Matching records are suggested on the next page.',
              )
        }}
      </div>

      <div class="flex flex-col gap-4">
        <div v-if="isDeal" class="flex flex-col gap-1.5">
          <FormControl
            v-model="contact"
            type="select"
            :label="__('Who is making the request?')"
            :options="contactOptions"
            :placeholder="__('Pick one of the contacts on this deal')"
            required
          />
          <div
            v-if="dealLoaded && !contactOptions.length"
            class="text-sm text-ink-amber-7"
          >
            {{
              __(
                'This deal has no contacts. Log the request from the contact or lead instead.',
              )
            }}
          </div>
        </div>

        <div class="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <FormControl
            v-model="channel"
            type="select"
            :label="__('How it arrived')"
            :options="channelOptions"
            :placeholder="__('Select')"
            required
          />
          <FormControl
            v-model="receivedOn"
            type="date"
            :label="__('Date received')"
            required
          />
        </div>

        <FormControl
          v-model="requesterNames"
          type="text"
          :label="__('Requester name(s)')"
          :placeholder="__('Name as written in the request')"
        />

        <div class="flex flex-col gap-2">
          <div class="text-xs text-ink-gray-5">
            {{ __('Emails and phones') }}
          </div>
          <div
            v-for="(row, index) in identifiers"
            :key="index"
            class="flex items-center gap-2"
          >
            <FormControl
              v-model="row.kind"
              type="select"
              class="w-28 shrink-0"
              :options="kindOptions"
            />
            <FormControl
              v-model="row.value"
              class="flex-1"
              type="text"
              :placeholder="
                row.kind === 'Phone' ? __('Phone number') : __('Email address')
              "
            />
            <Button
              variant="ghost"
              icon="lucide-x"
              :tooltip="__('Remove')"
              @click="identifiers.splice(index, 1)"
            />
          </div>
          <div>
            <Button
              variant="subtle"
              size="sm"
              icon-left="lucide-plus"
              :label="__('Add email or phone')"
              @click="identifiers.push({ kind: 'Email', value: '' })"
            />
          </div>
          <div class="text-sm text-ink-gray-5">
            {{
              __(
                'Details held on the lead or contact are added as well. Any of them can be left out on the next page.',
              )
            }}
          </div>
        </div>

        <FormControl
          v-model="originalMessage"
          type="textarea"
          :label="__('Original message')"
          :placeholder="__('Paste the request as it was received')"
          :rows="5"
        />
      </div>
    </template>
    <template #actions>
      <div class="flex items-center justify-between gap-2">
        <div><ErrorMessage :message="error" /></div>
        <div class="flex gap-2">
          <Button :label="__('Cancel')" @click="close" />
          <Button
            variant="solid"
            :label="__('Log request')"
            :disabled="!canSubmit"
            :loading="saving"
            @click="submit"
          />
        </div>
      </div>
    </template>
  </Dialog>
</template>

<script setup>
import {
  buildCreateRequest,
  CHANNELS,
  canLogRequest,
  contactChoices,
  errorText,
  IDENTIFIER_KINDS,
  recordIdentifiers,
  recordPersonName,
  startRecord,
} from '@/utils/erasureRequest'
import { call, dayjs, Dialog, toast } from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'

const props = defineProps({
  // Where the request starts. A lead or a contact is the requester itself; on
  // a deal the requester is picked from the deal's contacts. Blank = a form
  // that starts from nothing.
  startDoctype: { type: String, default: '' },
  startName: { type: String, default: '' },
})

const show = defineModel({ type: Boolean })
const router = useRouter()

const channel = ref('')
const receivedOn = ref('')
const requesterNames = ref('')
const originalMessage = ref('')
const identifiers = ref([])
const contact = ref('')
const dealContacts = ref([])
const dealLoaded = ref(false)
const error = ref('')
const saving = ref(false)

// The name put in the field by this form, so a later pick can replace it
// without overwriting what a person typed.
let autoName = ''
let loadToken = 0

const isDeal = computed(() => props.startDoctype === 'CRM Deal')
const contactOptions = computed(() => contactChoices(dealContacts.value))
const channelOptions = CHANNELS.map((value) => ({ value, label: __(value) }))
const kindOptions = IDENTIFIER_KINDS.map((value) => ({
  value,
  label: __(value),
}))

const start = computed(() =>
  startRecord(props.startDoctype, props.startName, contact.value),
)
const canSubmit = computed(() =>
  canLogRequest({
    channel: channel.value,
    receivedOn: receivedOn.value,
    startReady: !isDeal.value || Boolean(contact.value),
  }),
)

watch(show, (open) => {
  if (open) reset()
})
if (show.value) reset()

watch(() => [start.value.startDoctype, start.value.startName], loadStart)

function reset() {
  channel.value = ''
  receivedOn.value = dayjs().format('YYYY-MM-DD')
  requesterNames.value = ''
  originalMessage.value = ''
  identifiers.value = []
  contact.value = ''
  dealContacts.value = []
  dealLoaded.value = false
  error.value = ''
  autoName = ''
  if (isDeal.value) loadDeal()
  else loadStart()
}

async function loadDeal() {
  const token = ++loadToken
  try {
    const deal = await call('frappe.client.get', {
      doctype: 'CRM Deal',
      name: props.startName,
    })
    if (token !== loadToken) return
    dealContacts.value = deal.contacts || []
    dealLoaded.value = true
    // one contact: nothing to choose
    if (contactOptions.value.length === 1) {
      contact.value = contactOptions.value[0].value
    }
  } catch (e) {
    error.value = errorText(e)
  }
}

// Show what the record holds, so it can be corrected before submitting. The
// server adds the record's details itself when it creates the request.
async function loadStart() {
  const { startDoctype, startName } = start.value
  const token = ++loadToken
  if (!startDoctype || !startName) {
    identifiers.value = []
    if (requesterNames.value === autoName) requesterNames.value = ''
    autoName = ''
    return
  }
  try {
    const doc = await call('frappe.client.get', {
      doctype: startDoctype,
      name: startName,
    })
    if (token !== loadToken) return
    identifiers.value = recordIdentifiers(startDoctype, doc)
    const name = recordPersonName(startDoctype, doc)
    if (!requesterNames.value || requesterNames.value === autoName) {
      requesterNames.value = name
    }
    autoName = name
  } catch (e) {
    error.value = errorText(e)
  }
}

function close() {
  show.value = false
}

async function submit() {
  if (!canSubmit.value) return
  saving.value = true
  error.value = ''
  try {
    const name = await call(
      'crm.api.erasure.create_request',
      buildCreateRequest({
        channel: channel.value,
        receivedOn: receivedOn.value,
        requesterNames: requesterNames.value,
        originalMessage: originalMessage.value,
        identifiers: identifiers.value,
        ...start.value,
      }),
    )
    toast.success(__('Request {0} logged', [name]))
    close()
    router.push({ name: 'ErasureRequest', params: { requestId: name } })
  } catch (e) {
    error.value = errorText(e)
  } finally {
    saving.value = false
  }
}
</script>
