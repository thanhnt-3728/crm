<template>
  <Button
    v-if="can.close"
    iconLeft="lucide-mail"
    :label="__('Outcome email')"
    @click="showMail = true"
  />
  <Button
    v-if="can.submit"
    variant="solid"
    :label="__('Submit to Compliance')"
    :loading="submitting"
    @click="confirmSubmit"
  />
  <Button
    v-if="can.decline"
    theme="red"
    :label="__('Decline')"
    @click="showDecline = true"
  />
  <Button
    v-if="can.approve"
    variant="solid"
    :label="__('Approve')"
    @click="showApproval = true"
  />
  <Button
    v-if="can.close"
    variant="solid"
    :label="__('Close')"
    @click="showClose = true"
  />
  <ApprovalDialog
    v-model="showApproval"
    :request="request"
    @updated="(r) => emit('updated', r)"
  />
  <DeclineDialog
    v-model="showDecline"
    :request="request"
    @updated="(r) => emit('updated', r)"
  />
  <CloseDialog
    v-model="showClose"
    :request="request"
    @updated="(r) => emit('updated', r)"
    @compose="composeFromClose"
  />
  <OutcomeEmailDialog v-model="showMail" :request="request" />
</template>

<script setup>
import ApprovalDialog from '@/components/ErasureRequests/ApprovalDialog.vue'
import CloseDialog from '@/components/ErasureRequests/CloseDialog.vue'
import DeclineDialog from '@/components/ErasureRequests/DeclineDialog.vue'
import OutcomeEmailDialog from '@/components/ErasureRequests/OutcomeEmailDialog.vue'
import { runAction } from '@/components/ErasureRequests/erasureApi'
import { createDialog } from '@/utils/dialogs'
import { toast } from 'frappe-ui'
import { computed, ref } from 'vue'

const props = defineProps({
  request: { type: Object, required: true },
})
// `updated` carries the request, or for a logger who just submitted, only its status and dates.
const emit = defineEmits(['updated'])

// Buttons only render what the server's flags allow; every endpoint checks again.
const can = computed(() => props.request.can || {})

const showApproval = ref(false)
const showDecline = ref(false)
const showClose = ref(false)
const showMail = ref(false)
const submitting = ref(false)

function composeFromClose() {
  showClose.value = false
  showMail.value = true
}

function confirmSubmit() {
  createDialog({
    title: __('Submit to Compliance?'),
    message: __(
      'Compliance will review the matches and sign off. You will no longer be able to edit the request.',
    ),
    actions: [
      {
        label: __('Submit'),
        variant: 'solid',
        onClick: async ({ close }) => {
          close()
          submitting.value = true
          const result = await runAction('requests.submit_request', {
            name: props.request.name,
          })
          submitting.value = false
          if (!result) return
          toast.success(__('Submitted to Compliance'))
          emit('updated', result)
        },
      },
    ],
  })
}
</script>
