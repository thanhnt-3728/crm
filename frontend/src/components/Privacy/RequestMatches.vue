<template>
  <div class="flex flex-col gap-2">
    <div
      v-if="!matches.length"
      class="rounded border border-dashed px-3 py-4 text-p-base text-ink-gray-5"
    >
      {{ __('No matching records found.') }}
    </div>
    <div v-else class="overflow-x-auto rounded border">
      <table class="w-full text-base text-ink-gray-8">
        <thead class="bg-surface-gray-1 text-sm text-ink-gray-5">
          <tr>
            <th class="px-3 py-2 text-left font-normal">{{ __('Confirm') }}</th>
            <th class="px-3 py-2 text-left font-normal">{{ __('Record') }}</th>
            <th class="px-3 py-2 text-left font-normal">{{ __('Type') }}</th>
            <th class="px-3 py-2 text-left font-normal">
              {{ __('Why it matched') }}
            </th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in matches" :key="row.name" class="border-t">
            <td class="px-3 py-2">
              <FormControl
                type="checkbox"
                :modelValue="!!row.confirmed"
                :disabled="!canEdit || busy"
                :aria-label="__('Confirm {0}', [row.reference_name])"
                @update:modelValue="
                  (value) =>
                    emit('save', {
                      matches: [{ name: row.name, confirmed: value ? 1 : 0 }],
                    })
                "
              />
            </td>
            <td class="px-3 py-2">
              <router-link
                v-if="matchRoute(row.reference_doctype, row.reference_name)"
                :to="matchRoute(row.reference_doctype, row.reference_name)"
                class="text-ink-gray-9 underline-offset-2 hover:underline"
                target="_blank"
              >
                {{ row.title || row.reference_name }}
              </router-link>
              <span v-else>{{ row.title || row.reference_name }}</span>
              <div class="text-sm text-ink-gray-5">
                {{ row.reference_name }}
              </div>
            </td>
            <td class="px-3 py-2">{{ doctypeLabel(row.reference_doctype) }}</td>
            <td class="px-3 py-2 text-ink-gray-6">{{ row.reason }}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <div v-if="canEdit" class="flex flex-col gap-2">
      <form class="flex items-end gap-2" @submit.prevent="addMatch">
        <FormControl
          v-model="doctype"
          type="select"
          class="w-32"
          :options="[
            { label: __('Lead'), value: 'CRM Lead' },
            { label: __('Contact'), value: 'Contact' },
            { label: __('Deal'), value: 'CRM Deal' },
          ]"
        />
        <FormControl
          v-model="referenceName"
          type="text"
          class="flex-1"
          :placeholder="__('Record ID')"
        />
        <Button
          type="submit"
          :label="__('Add record')"
          :disabled="!referenceName.trim() || busy"
        />
        <Button
          :label="__('Refresh matches')"
          iconLeft="lucide-refresh-cw"
          :disabled="busy"
          @click="emit('refresh')"
        />
      </form>
    </div>
  </div>
</template>

<script setup>
import { matchRoute } from '@/utils/erasureRequest'
import { computed, ref } from 'vue'

const props = defineProps({
  doc: { type: Object, required: true },
  canEdit: { type: Boolean, default: false },
  busy: { type: Boolean, default: false },
})
const emit = defineEmits(['save', 'refresh'])

const doctype = ref('CRM Lead')
const referenceName = ref('')

const matches = computed(() => props.doc.matches || [])

const DOCTYPE_LABELS = {
  'CRM Lead': 'Lead',
  'CRM Deal': 'Deal',
  Contact: 'Contact',
}

function doctypeLabel(value) {
  return __(DOCTYPE_LABELS[value] || value)
}

function addMatch() {
  const name = referenceName.value.trim()
  if (!name) return
  emit('save', {
    matches: [
      { reference_doctype: doctype.value, reference_name: name, confirmed: 1 },
    ],
  })
  referenceName.value = ''
}
</script>
