<template>
  <div class="flex flex-col gap-2">
    <div
      v-if="!checklist.length"
      class="rounded border border-dashed px-3 py-4 text-p-base text-ink-gray-5"
    >
      {{ __('No checklist items yet.') }}
    </div>
    <ul v-else class="divide-y rounded border">
      <li
        v-for="item in checklist"
        :key="item.name"
        class="flex items-center gap-3 px-3 py-2 text-base text-ink-gray-8"
      >
        <FormControl
          type="checkbox"
          :modelValue="!!item.done"
          :disabled="!canManage || busy"
          :aria-label="item.description"
          @update:modelValue="
            (value) =>
              emit('save', {
                checklist: [{ name: item.name, done: value ? 1 : 0 }],
              })
          "
        />
        <div class="flex-1" :class="item.done ? 'text-ink-gray-5' : ''">
          {{ item.description }}
        </div>
        <div v-if="item.done && item.done_by" class="text-sm text-ink-gray-5">
          {{ doneBy(item) }}
        </div>
      </li>
    </ul>

    <form
      v-if="canManage"
      class="flex items-end gap-2"
      @submit.prevent="addItem"
    >
      <FormControl
        v-model="description"
        type="text"
        class="flex-1"
        :placeholder="__('Add a checklist item')"
      />
      <Button
        type="submit"
        :label="__('Add')"
        :disabled="!description.trim() || busy"
      />
    </form>
  </div>
</template>

<script setup>
import { usersStore } from '@/stores/users'
import { formatDate } from '@/utils'
import { computed, ref } from 'vue'

const props = defineProps({
  doc: { type: Object, required: true },
  canManage: { type: Boolean, default: false },
  busy: { type: Boolean, default: false },
})
const emit = defineEmits(['save'])

const { getUser } = usersStore()
const description = ref('')

const checklist = computed(() => props.doc.checklist || [])

function doneBy(item) {
  const who = getUser(item.done_by)?.full_name || item.done_by
  return `${who}, ${formatDate(item.done_on)}`
}

function addItem() {
  const text = description.value.trim()
  if (!text) return
  emit('save', { checklist: [{ description: text }] })
  description.value = ''
}
</script>
