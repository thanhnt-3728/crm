<template>
  <Dialog v-model:open="show" :title="__('Approve erasure')" size="2xl">
    <template #default>
      <div v-if="loading" class="py-6 text-center text-ink-gray-5">
        {{ __('Loading preview...') }}
      </div>
      <div v-else class="flex flex-col gap-3">
        <div class="text-p-sm text-ink-gray-7">
          {{
            __(
              'Approving permanently erases or anonymizes the records below. This cannot be undone. Tick Exclude on any record that must be kept.',
            )
          }}
        </div>
        <div
          v-if="newCount"
          class="rounded bg-surface-amber-2 p-2 text-p-sm text-ink-amber-3"
        >
          {{
            __(
              '{0} new record(s) found since the request was logged. Review them before approving.',
              [newCount],
            )
          }}
        </div>
        <ErasureIdentifierWarnings
          :items="preview.identifiers_not_on_subject"
        />
        <ErasureMatchesList
          :groups="groups"
          :excluded="excluded"
          :hidden="preview.hidden"
          selectable
          @toggle="(key) => (excluded = toggleExclusion(excluded, key))"
        />
        <Checkbox
          v-if="newCount"
          v-model="reviewed"
          :label="__('I reviewed the {0} new records', [newCount])"
        />
        <FormControl
          v-model="typed"
          type="text"
          autocomplete="off"
          :label="__('Type {0} to confirm', [requestName])"
        />
      </div>
      <ErrorMessage class="mt-3" :message="error" />
    </template>
    <template #actions>
      <div class="flex justify-end gap-2">
        <Button :label="__('Cancel')" @click="show = false" />
        <Button
          variant="solid"
          theme="red"
          :label="__('Approve and erase')"
          :disabled="loading || !canApprove"
          :loading="busy"
          @click="approve"
        />
      </div>
    </template>
  </Dialog>
</template>

<script setup>
import {
  Dialog,
  FormControl,
  ErrorMessage,
  Button,
  Checkbox,
  call,
  toast,
} from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import ErasureIdentifierWarnings from '@/components/Erasure/erasure-identifier-warnings.vue'
import ErasureMatchesList from '@/components/Erasure/erasure-matches-list.vue'
import {
  canConfirmApproval,
  countNewRows,
  isStalePreviewError,
  serverMessage,
  sortNewFirst,
  toggleExclusion,
  excludedKeys,
} from '@/utils/erasure-matches'

const props = defineProps({
  requestName: { type: String, required: true },
})
const emit = defineEmits(['approved'])
const show = defineModel({ type: Boolean })

const loading = ref(false)
const busy = ref(false)
const error = ref('')
const typed = ref('')
const reviewed = ref(false)
const preview = ref({ groups: [], hidden: {}, preview_hash: '' })
const excluded = ref(new Set())

const groups = computed(() => sortNewFirst(preview.value.groups))
const newCount = computed(() => countNewRows(groups.value))
const canApprove = computed(() =>
  canConfirmApproval({
    typed: typed.value,
    name: props.requestName,
    newCount: newCount.value,
    reviewed: reviewed.value,
  }),
)

async function loadPreview() {
  loading.value = true
  error.value = ''
  reviewed.value = false
  try {
    preview.value = await call('crm.api.erasure.get_approval_preview', {
      name: props.requestName,
    })
    excluded.value = excludedKeys(groups.value)
  } catch (e) {
    error.value = serverMessage(e, __('Could not load the preview'))
  } finally {
    loading.value = false
  }
}

watch(show, (open) => {
  if (!open) return
  typed.value = ''
  loadPreview()
})

async function approve() {
  if (!canApprove.value) return
  busy.value = true
  error.value = ''
  try {
    await call('crm.api.erasure.approve', {
      name: props.requestName,
      confirm_name: typed.value.trim(),
      excluded: [...excluded.value],
      preview_hash: preview.value.preview_hash,
    })
    toast.success(__('Approved. The erasure is running.'))
    show.value = false
    emit('approved')
  } catch (e) {
    // One message only: the toast. A stale preview is reloaded for another look.
    toast.error(serverMessage(e, __('Could not approve the request')))
    if (isStalePreviewError(e)) {
      typed.value = ''
      await loadPreview()
    }
  } finally {
    busy.value = false
  }
}
</script>
