<template>
  <div
    v-if="draft"
    class="flex items-center justify-between gap-2 rounded bg-surface-amber-2 p-2 text-p-sm text-ink-amber-3"
  >
    <span>
      {{ __('You already have a draft request for this record: {0}', [draft]) }}
    </span>
    <Button :label="__('Open it')" @click="openDraft" />
  </div>
</template>

<script setup>
import { Button, call } from 'frappe-ui'
import { ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { sessionStore } from '@/stores/session'

const props = defineProps({
  sourceDoctype: { type: String, required: true },
  sourceDocname: { type: String, required: true },
  active: { type: Boolean, default: false },
})
const emit = defineEmits(['open'])
const router = useRouter()
const { user } = sessionStore()
const draft = ref('')

// Look for the user's own unfinished request each time the dialog opens.
watch(
  () => props.active,
  async (active) => {
    draft.value = ''
    if (!active) return
    try {
      const rows = await call('frappe.client.get_list', {
        doctype: 'CRM Erasure Request',
        fields: ['name'],
        filters: {
          source_doctype: props.sourceDoctype,
          source_docname: props.sourceDocname,
          status: 'Draft',
          owner: user,
        },
        limit_page_length: 1,
      })
      draft.value = rows?.[0]?.name || ''
    } catch {
      draft.value = '' // the notice is a convenience; logging still works
    }
  },
  { immediate: true },
)

function openDraft() {
  emit('open')
  router.push({ name: 'Erasure Request', params: { name: draft.value } })
}
</script>
