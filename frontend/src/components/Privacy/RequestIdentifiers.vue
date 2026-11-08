<template>
  <div class="flex flex-col gap-2">
    <div
      v-if="!identifiers.length"
      class="rounded border border-dashed px-3 py-4 text-p-base text-ink-gray-5"
    >
      {{ __('No email addresses or phone numbers yet.') }}
    </div>
    <div v-else class="overflow-x-auto rounded border">
      <table class="w-full text-base text-ink-gray-8">
        <thead class="bg-surface-gray-1 text-sm text-ink-gray-5">
          <tr>
            <th class="px-3 py-2 text-left font-normal">{{ __('Type') }}</th>
            <th class="px-3 py-2 text-left font-normal">{{ __('Value') }}</th>
            <th class="px-3 py-2 text-left font-normal">{{ __('Records') }}</th>
            <th class="px-3 py-2 text-left font-normal">{{ __('Emails') }}</th>
            <th class="px-3 py-2 text-left font-normal">{{ __('Calls') }}</th>
            <th class="px-3 py-2 text-left font-normal">{{ __('Exclude') }}</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="row in identifiers"
            :key="row.name"
            class="border-t"
            :class="row.excluded ? 'text-ink-gray-5' : ''"
          >
            <td class="px-3 py-2">{{ __(row.kind) }}</td>
            <td class="px-3 py-2" :class="row.excluded ? 'line-through' : ''">
              {{ row.value }}
            </td>
            <td class="px-3 py-2">{{ usageFor(row).records }}</td>
            <td class="px-3 py-2">{{ usageFor(row).emails }}</td>
            <td class="px-3 py-2">{{ usageFor(row).calls }}</td>
            <td class="px-3 py-2">
              <FormControl
                type="checkbox"
                :modelValue="!!row.excluded"
                :disabled="!canEdit || busy"
                :aria-label="__('Exclude {0}', [row.value])"
                @update:modelValue="
                  (value) =>
                    emit('save', {
                      identifiers: [
                        { name: row.name, excluded: value ? 1 : 0 },
                      ],
                    })
                "
              />
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <form
      v-if="canEdit"
      class="flex items-end gap-2"
      @submit.prevent="addIdentifier"
    >
      <FormControl
        v-model="kind"
        type="select"
        class="w-32"
        :options="[
          { label: __('Email'), value: 'Email' },
          { label: __('Phone'), value: 'Phone' },
        ]"
      />
      <FormControl
        v-model="value"
        type="text"
        class="flex-1"
        :placeholder="
          kind === 'Email' ? __('name@example.com') : __('Phone number')
        "
      />
      <Button
        type="submit"
        :label="__('Add')"
        :disabled="!value.trim() || busy"
      />
    </form>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'

const props = defineProps({
  doc: { type: Object, required: true },
  usage: { type: Array, default: () => [] },
  canEdit: { type: Boolean, default: false },
  busy: { type: Boolean, default: false },
})
const emit = defineEmits(['save'])

const kind = ref('Email')
const value = ref('')

const identifiers = computed(() => props.doc.identifiers || [])

function usageFor(row) {
  const found = props.usage.find(
    (item) => item.kind === row.kind && item.value === row.value,
  )
  return { records: 0, emails: 0, calls: 0, ...found }
}

function addIdentifier() {
  const typed = value.value.trim()
  if (!typed) return
  emit('save', { identifiers: [{ kind: kind.value, value: typed }] })
  value.value = ''
}
</script>
