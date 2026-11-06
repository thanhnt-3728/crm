<template>
  <Dialog
    v-model:open="show"
    :title="__('Log erasure request')"
    :size="step === 'review' ? '2xl' : 'xl'"
  >
    <template #default>
      <ErasureIdentifierForm
        v-if="step === 'details'"
        v-model:subject="subjectName"
        v-model:received-on="receivedOn"
        v-model:emails="emailsText"
        v-model:phones="phonesText"
        :source-doctype="sourceDoctype"
        :source-docname="sourceDocname"
        :active="show"
        :max-date="today"
        @open-draft="show = false"
      />
      <div v-else class="flex flex-col gap-3">
        <div class="text-p-sm text-ink-gray-6">
          {{
            __('Acknowledge by {0}, respond by {1}', [
              displayDate(preview.ack_due),
              displayDate(preview.response_due),
            ])
          }}
        </div>
        <div class="text-p-sm text-ink-gray-6">
          {{
            __(
              'Closing this window keeps the request as a Draft in the Erasure Requests list.',
            )
          }}
        </div>
        <ErasureIdentifierWarnings
          :items="preview.identifiers_not_on_subject"
        />
        <ErasureMatchesList
          :groups="preview.groups"
          :excluded="excluded"
          :hidden="preview.hidden"
          selectable
          @toggle="(key) => (excluded = toggleExclusion(excluded, key))"
        />
      </div>
      <ErrorMessage class="mt-3" :message="error" />
    </template>
    <template #actions>
      <div class="flex justify-end gap-2">
        <Button :label="__('Cancel')" @click="show = false" />
        <Button
          v-if="step === 'details'"
          variant="solid"
          :label="__('Find matches')"
          :loading="busy"
          @click="findMatches"
        />
        <Button
          v-else
          variant="solid"
          :label="__('Submit for approval')"
          :loading="busy"
          @click="submit"
        />
      </div>
    </template>
  </Dialog>
</template>

<script setup>
import { Dialog, ErrorMessage, Button, call, toast } from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import ErasureIdentifierForm from '@/components/Erasure/erasure-identifier-form.vue'
import ErasureIdentifierWarnings from '@/components/Erasure/erasure-identifier-warnings.vue'
import ErasureMatchesList from '@/components/Erasure/erasure-matches-list.vue'
import { displayDate } from '@/composables/erasure-display-date'
import { todayString } from '@/utils/erasure-deadlines'
import {
  prefillIdentifiers,
  sameKeys,
  serverMessage,
  toggleExclusion,
  excludedKeys,
} from '@/utils/erasure-matches'

const props = defineProps({
  sourceDoctype: { type: String, required: true },
  sourceDocname: { type: String, required: true },
  sourceDoc: { type: Object, default: () => ({}) },
})
const show = defineModel({ type: Boolean })
const router = useRouter()

const step = ref('details')
const busy = ref(false)
const error = ref('')
const subjectName = ref('')
const receivedOn = ref('')
const emailsText = ref('')
const phonesText = ref('')
const preview = ref({ groups: [], hidden: {} })
const excluded = ref(new Set())
const loggedExcluded = ref(new Set())
const today = computed(() => todayString())

const lines = (text) =>
  text
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)

// Prefill each time the dialog opens; nothing is kept between openings.
watch(show, (open) => {
  if (!open) return
  const prefill = prefillIdentifiers(props.sourceDoc, props.sourceDoctype)
  subjectName.value = prefill.subject_name
  emailsText.value = prefill.emails.join('\n')
  phonesText.value = prefill.phones.join('\n')
  receivedOn.value = ''
  step.value = 'details'
  error.value = ''
  excluded.value = new Set()
  preview.value = { groups: [], hidden: {} }
})

async function findMatches() {
  const emails = lines(emailsText.value)
  const phones = lines(phonesText.value)
  if (!subjectName.value.trim())
    return (error.value = __('Enter the name of the person'))
  if (!receivedOn.value)
    return (error.value = __('Enter the date the request was received'))
  if (receivedOn.value > today.value)
    return (error.value = __('The received date cannot be in the future'))
  if (!emails.length && !phones.length)
    return (error.value = __('Add at least one email address or phone number'))
  error.value = ''
  busy.value = true
  try {
    preview.value = await call('crm.api.erasure.log_request', {
      source_doctype: props.sourceDoctype,
      source_docname: props.sourceDocname,
      subject_name: subjectName.value.trim(),
      received_on: receivedOn.value,
      emails,
      phones,
    })
    excluded.value = excludedKeys(preview.value.groups)
    loggedExcluded.value = new Set(excluded.value)
    step.value = 'review'
  } catch (e) {
    error.value = serverMessage(e, __('Could not log the request'))
  } finally {
    busy.value = false
  }
}

async function submit() {
  busy.value = true
  error.value = ''
  try {
    if (!sameKeys(excluded.value, loggedExcluded.value)) {
      await call('crm.api.erasure.set_exclusions', {
        name: preview.value.name,
        excluded: [...excluded.value],
      })
    }
    const result = await call('crm.api.erasure.submit_for_approval', {
      name: preview.value.name,
    })
    toast.success(
      result.status === 'On Hold'
        ? __(
            'Request logged and put on hold: an open deal is linked to this person',
          )
        : __('Request submitted for approval'),
    )
    show.value = false
    router.push({ name: 'Erasure Request', params: { name: result.name } })
  } catch (e) {
    error.value = serverMessage(e, __('Could not submit the request'))
  } finally {
    busy.value = false
  }
}
</script>
