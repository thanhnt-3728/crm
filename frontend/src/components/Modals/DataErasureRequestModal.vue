<template>
  <Dialog v-model:open="show" :title="__('Request data erasure')" size="lg">
    <template #default>
      <div v-if="requests.loading" class="py-6 text-center text-ink-gray-5">
        {{ __('Loading...') }}
      </div>

      <div v-else-if="current" class="flex flex-col gap-3 text-p-base">
        <div class="flex items-center gap-2">
          <Badge
            :label="__(current.status)"
            :theme="statusTheme(current.status)"
            variant="subtle"
          />
          <span class="text-ink-gray-8">{{ current.name }}</span>
        </div>
        <p class="text-ink-gray-7">
          <template v-if="current.status === 'Pending Approval'">
            {{
              __(
                'An erasure request for {0} was logged on {1} and is waiting for the Privacy team. A response is due by {2}.',
                [
                  subjectName,
                  formatDate(current.received_on, undefined, true),
                  formatDate(current.respond_by, undefined, true),
                ],
              )
            }}
          </template>
          <template v-else>
            {{
              __(
                "{0}'s personal data was erased on {1}. The record is kept so pipeline and revenue reports don't change.",
                [subjectName, formatDate(current.decided_on, undefined, true)],
              )
            }}
          </template>
        </p>
      </div>

      <div v-else class="flex flex-col gap-4">
        <p class="text-p-base text-ink-gray-7">
          {{
            __(
              'Log this if {0} asked us to delete their personal data. The Privacy team reviews it and runs the erasure; nothing is deleted until they approve.',
              [subjectName],
            )
          }}
        </p>
        <div class="grid grid-cols-2 gap-3">
          <FormControl
            v-model="receivedOn"
            type="date"
            :label="__('Received on')"
            :max="today"
            required
          />
          <FormControl
            v-model="receivedVia"
            type="select"
            :label="__('Received via')"
            :options="channels"
          />
        </div>
        <FormControl
          v-model="notes"
          type="textarea"
          :label="__('Notes')"
          :description="
            __(
              'How the request reached us. Don\'t paste the person\'s message here.',
            )
          "
        />
        <p class="text-p-sm text-ink-gray-5">
          {{
            __(
              'The Privacy team must acknowledge the request within 10 business days and respond within 45 days of the date it was received.',
            )
          }}
        </p>
      </div>
    </template>
    <template #actions>
      <div class="flex items-center justify-between gap-2">
        <ErrorMessage :message="error" />
        <div class="flex gap-2">
          <Button
            :label="current ? __('Close') : __('Cancel')"
            @click="show = false"
          />
          <Button
            v-if="!current && !requests.loading"
            variant="solid"
            :label="__('Log request')"
            :loading="submitting"
            @click="submit"
          />
        </div>
      </div>
    </template>
  </Dialog>
</template>
<script setup>
import { formatDate } from '@/utils'
import {
  Badge,
  Dialog,
  ErrorMessage,
  FormControl,
  call,
  createResource,
  toast,
} from 'frappe-ui'
import { computed, ref } from 'vue'

const props = defineProps({
  doctype: { type: String, required: true },
  docname: { type: String, required: true },
  subjectName: { type: String, default: '' },
})

const emit = defineEmits(['logged'])

const show = defineModel({ type: Boolean })

const linkField = props.doctype === 'Contact' ? 'contact' : 'lead'
const today = new Date().toISOString().slice(0, 10)
const channels = ['Email', 'Phone', 'Web Form', 'In Person', 'Other'].map(
  (value) => ({ label: __(value), value }),
)

const receivedOn = ref(today)
const receivedVia = ref('Email')
const notes = ref('')
const error = ref('')
const submitting = ref(false)

const requests = createResource({
  url: 'crm.fcrm.doctype.crm_data_erasure_request.crm_data_erasure_request.get_requests',
  params: { [linkField]: props.docname },
  auto: true,
})

// A rejected request doesn't block logging a new one.
const current = computed(() =>
  (requests.data || []).find((r) => r.status !== 'Rejected'),
)

function statusTheme(status) {
  return status === 'Completed' ? 'green' : 'orange'
}

async function submit() {
  error.value = ''
  if (!receivedOn.value) {
    error.value = __('Received on is required')
    return
  }
  submitting.value = true
  try {
    const doc = await call('frappe.client.insert', {
      doc: {
        doctype: 'CRM Data Erasure Request',
        [linkField]: props.docname,
        received_on: receivedOn.value,
        received_via: receivedVia.value,
        notes: notes.value,
      },
    })
    toast.success(__('Erasure request {0} logged', [doc.name]))
    emit('logged', doc)
    await requests.reload()
  } catch (e) {
    error.value = e?.messages?.[0] || e?.message || __('Could not log request')
  } finally {
    submitting.value = false
  }
}
</script>
