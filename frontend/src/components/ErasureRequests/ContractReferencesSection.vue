<template>
  <section class="flex flex-col gap-3 rounded-lg border p-4">
    <div class="flex items-center justify-between">
      <div>
        <h3 class="text-lg-medium text-ink-gray-9">
          {{ __('Contract references') }}
        </h3>
        <p class="text-p-sm text-ink-gray-6">
          {{
            __(
              'If the person signed a contract or order, only the name and the reference are kept, for the retention period counsel set.',
            )
          }}
        </p>
      </div>
      <Button
        v-if="editable && dirty"
        variant="solid"
        :label="__('Save')"
        :loading="saving"
        @click="save"
      />
    </div>
    <div
      v-for="(reference, index) in references"
      :key="index"
      class="flex gap-2"
    >
      <FormControl
        v-model="references[index]"
        class="flex-1"
        type="text"
        :disabled="!editable"
        :placeholder="__('Contract or order reference')"
      />
      <Button
        v-if="editable"
        icon="lucide-x"
        variant="ghost"
        :tooltip="__('Remove')"
        @click="references.splice(index, 1)"
      />
    </div>
    <div v-if="editable">
      <Button
        iconLeft="lucide-plus"
        :label="__('Add reference')"
        @click="references.push('')"
      />
    </div>
  </section>
</template>

<script setup>
import { runAction } from '@/components/ErasureRequests/erasureApi'
import { FormControl, toast } from 'frappe-ui'
import { computed, ref, watch } from 'vue'

const props = defineProps({
  request: { type: Object, required: true },
  editable: { type: Boolean, default: false },
})
const emit = defineEmits(['updated'])

const saved = () =>
  (props.request.contract_references || []).map((row) => row.reference)
const references = ref(saved())
const saving = ref(false)

watch(
  () => props.request.modified,
  () => (references.value = saved()),
)

const cleaned = () =>
  references.value.map((value) => value.trim()).filter(Boolean)
const dirty = computed(
  () => JSON.stringify(cleaned()) !== JSON.stringify(saved()),
)

async function save() {
  saving.value = true
  const result = await runAction('review.set_contract_references', {
    name: props.request.name,
    references: cleaned(),
  })
  saving.value = false
  if (!result) return
  toast.success(__('Contract references saved'))
  emit('updated', result)
}
</script>
