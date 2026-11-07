<template>
  <Dialog
    v-model:open="show"
    :title="__('Outcome email for {0}', [request.name])"
    size="3xl"
  >
    <template #default>
      <div class="flex flex-col gap-2">
        <p class="text-p-sm text-ink-gray-6">
          {{
            __(
              'Fill in every [COMPLIANCE: ...] part of the Erasure outcome template before sending. The email is kept on the request until it closes.',
            )
          }}
        </p>
        <!-- Created on open so the first address is picked up. Nothing here is written to local storage. -->
        <div v-if="show" class="overflow-hidden rounded-lg border">
          <EmailEditor
            ref="editorRef"
            v-model:content="content"
            v-model:attachments="attachments"
            :model-value="mailDoc"
            doctype="CRM Erasure Request"
            :subject="''"
            :submitButtonProps="{
              variant: 'solid',
              onClick: send,
              disabled: !content || sending,
            }"
            :discardButtonProps="{ onClick: () => (show = false) }"
            :placeholder="__('Write the answer to the requester')"
          />
        </div>
      </div>
    </template>
  </Dialog>
</template>

<script setup>
import EmailEditor from '@/components/EmailEditor.vue'
import { runAction } from '@/components/ErasureRequests/erasureApi'
import { errorText } from '@/utils/erasureRequestDisplay'
import { Dialog, call, toast } from 'frappe-ui'
import { computed, ref, watch } from 'vue'

const TEMPLATE = 'Erasure outcome'

const props = defineProps({
  request: { type: Object, required: true },
})
const emit = defineEmits(['sent'])

const show = defineModel({ type: Boolean })

const editorRef = ref(null)
const content = ref('')
const attachments = ref([])
const sending = ref(false)

const firstEmail = computed(
  () =>
    props.request.identifiers?.find(
      (row) => row.kind === 'Email' && !row.excluded,
    )?.value || '',
)
const mailDoc = computed(() => ({
  name: props.request.name,
  email: firstEmail.value,
}))

watch(show, () => {
  content.value = ''
  attachments.value = []
})

// The editor mounts when the dialog opens: start from the Erasure outcome template. A missing template or
// permission leaves a blank email and says why.
watch(editorRef, async (editor) => {
  if (!editor) return
  try {
    const data = await call(
      'frappe.email.doctype.email_template.email_template.get_email_template',
      {
        template_name: TEMPLATE,
        doc: { name: props.request.name },
      },
    )
    if (data.subject) editor.subject = data.subject
    if (data.message) content.value = data.message
  } catch (error) {
    toast.error(errorText(error))
  }
})

// Goes to the requester's own addresses only; CC, BCC and attachments are not part of this email.
async function send() {
  const editor = editorRef.value
  if (!editor?.toEmails?.length) {
    toast.error(__('Add at least one recipient'))
    return
  }
  if (
    editor.ccEmails?.length ||
    editor.bccEmails?.length ||
    attachments.value.length
  ) {
    toast.error(__('The outcome email cannot have CC, BCC or attachments'))
    return
  }
  sending.value = true
  const result = await runAction('outcome_email.send_outcome_email', {
    name: props.request.name,
    subject: editor.subject,
    content: content.value,
    recipients: editor.toEmails,
  })
  sending.value = false
  if (!result) return
  toast.success(
    __('Email queued. The request can close once it has been sent.'),
  )
  show.value = false
  emit('sent')
}
</script>
