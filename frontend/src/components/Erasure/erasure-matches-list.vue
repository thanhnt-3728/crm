<template>
  <div class="flex flex-col gap-3">
    <div
      v-if="!groups.length"
      class="rounded border border-outline-gray-2 p-3 text-p-sm text-ink-gray-6"
    >
      {{ __('No records of this person were found.') }}
    </div>
    <div
      v-for="group in groups"
      :key="group.doctype"
      class="rounded border border-outline-gray-2"
    >
      <div
        class="flex items-center justify-between bg-surface-gray-2 px-3 py-1.5 text-sm font-medium text-ink-gray-8"
      >
        <span>{{ __(group.doctype) }}</span>
        <span class="text-ink-gray-6">{{ group.count }}</span>
      </div>
      <ul class="divide-y divide-outline-gray-1">
        <li
          v-for="row in group.rows"
          :key="row.key"
          class="flex items-start gap-2 px-3 py-2 text-p-sm"
        >
          <Checkbox
            v-if="selectable"
            class="mt-0.5"
            :modelValue="!isToggleable(row) || excluded.has(row.key)"
            :disabled="!isToggleable(row)"
            :label="__('Exclude')"
            @update:modelValue="emit('toggle', row.key)"
          />
          <div class="min-w-0 flex-1">
            <div class="truncate text-ink-gray-8">
              {{ row.title || row.ref_name }}
              <Badge
                v-if="row.new_since_logging"
                class="ml-1"
                theme="orange"
                variant="solid"
                :label="__('New')"
              />
              <Badge
                v-if="!selectable && row.excluded"
                class="ml-1"
                theme="gray"
                :label="__('Excluded')"
              />
            </div>
            <div class="truncate text-ink-gray-5">
              {{
                isToggleable(row) ? row.reason : __('Excluded with its parent')
              }}
            </div>
          </div>
        </li>
      </ul>
      <div
        v-if="group.unreadable"
        class="border-t border-outline-gray-1 px-3 py-2 text-p-sm text-ink-gray-5"
      >
        {{ __('{0} more you cannot view', [group.unreadable]) }}
      </div>
    </div>
    <div v-if="hiddenEntries.length" class="text-p-sm text-ink-gray-6">
      <div class="font-medium">{{ __('Also removed from system copies') }}</div>
      <div v-for="[doctype, count] in hiddenEntries" :key="doctype">
        {{ __(doctype) }}: {{ count }}
      </div>
    </div>
  </div>
</template>

<script setup>
import { Badge, Checkbox } from 'frappe-ui'
import { computed } from 'vue'
import { isToggleable } from '@/utils/erasure-matches'

const props = defineProps({
  // Groups from groupMatches() or the preview payload: {doctype, count, rows[{key,...}]}.
  groups: { type: Array, default: () => [] },
  excluded: { type: Set, default: () => new Set() },
  hidden: { type: Object, default: () => ({}) },
  selectable: { type: Boolean, default: false },
})
const emit = defineEmits(['toggle'])

const hiddenEntries = computed(() =>
  Object.entries(props.hidden || {}).filter(([, count]) => count > 0),
)
</script>
