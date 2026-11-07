<template>
  <Dialog
    v-model:open="show"
    :title="__('Approve erasure of {0}', [request.name])"
    size="2xl"
  >
    <template #default>
      <div v-if="loading" class="flex justify-center p-8">
        <LoadingIndicator class="size-5" />
      </div>
      <ErrorMessage v-else-if="error" :message="error" />
      <div v-else-if="preview" class="flex flex-col gap-4">
        <Alert
          v-if="preview.blocked_by.length"
          theme="amber"
          :title="__('An open deal still lists the person')"
          :description="
            __(
              'Approval is blocked until these deals are closed or the person is removed from them. Use Re-check hold afterwards.',
            )
          "
        />
        <ul
          v-if="preview.blocked_by.length"
          class="flex flex-wrap gap-x-3 text-p-sm"
        >
          <li v-for="deal in preview.blocked_by" :key="deal.name">
            <RouterLink
              :to="{ name: 'Deal', params: { dealId: deal.name } }"
              target="_blank"
              class="text-ink-gray-7 hover:underline"
            >
              {{ deal.name }}
            </RouterLink>
          </li>
        </ul>
        <div class="max-h-[45vh] overflow-y-auto pr-1">
          <ErasurePreviewSections :preview="preview" />
        </div>
        <Alert
          theme="red"
          :title="__('This cannot be undone')"
          :description="
            __(
              'Approving erases the personal data listed above everywhere the CRM holds it. There is no undo.',
            )
          "
        />
        <FormControl
          v-model="typed"
          type="text"
          :label="__('Type {0} to confirm', [request.name])"
          :placeholder="request.name"
          autocomplete="off"
        />
      </div>
    </template>
    <template #actions>
      <div class="flex justify-end gap-2">
        <Button :label="__('Cancel')" @click="show = false" />
        <Button
          variant="solid"
          theme="red"
          :label="__('Approve and erase')"
          :loading="approving"
          :disabled="!canApprove"
          @click="approve"
        />
      </div>
    </template>
  </Dialog>
</template>

<script setup>
import ErasurePreviewSections from '@/components/ErasureRequests/ErasurePreviewSections.vue'
import { erasureCall, runAction } from '@/components/ErasureRequests/erasureApi'
import { confirmationMatches, errorText } from '@/utils/erasureRequestDisplay'
import {
  Alert,
  Dialog,
  ErrorMessage,
  FormControl,
  LoadingIndicator,
  toast,
} from 'frappe-ui'
import { computed, ref, watch } from 'vue'

const props = defineProps({
  request: { type: Object, required: true },
})
const emit = defineEmits(['updated'])

const show = defineModel({ type: Boolean })
const preview = ref(null)
const loading = ref(false)
const error = ref('')
const typed = ref('')
const approving = ref(false)

// Approvable only when no deal holds the request and the exact number was typed.
const canApprove = computed(
  () =>
    Boolean(preview.value) &&
    !preview.value.blocked_by.length &&
    confirmationMatches(typed.value, props.request.name),
)

// Each opening builds a fresh preview: it must show what would run now.
watch(show, async (open) => {
  typed.value = ''
  if (!open) return
  loading.value = true
  error.value = ''
  preview.value = null
  try {
    preview.value = await erasureCall('review.get_erasure_preview', {
      name: props.request.name,
    })
  } catch (e) {
    error.value = errorText(e)
  }
  loading.value = false
})

async function approve() {
  approving.value = true
  const result = await runAction('review.approve_request', {
    name: props.request.name,
    typed_number: typed.value,
  })
  approving.value = false
  if (!result) return
  show.value = false
  if (result.status === 'On Hold') {
    toast.info(
      __(
        'An open deal now lists the person, so the request is On Hold and nothing was erased',
      ),
    )
  } else {
    toast.success(__('Erasure queued'))
  }
  emit('updated', result)
}
</script>
