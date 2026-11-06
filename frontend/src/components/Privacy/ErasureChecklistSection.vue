<template>
  <section>
    <div class="mb-1 text-lg-medium text-ink-gray-9">
      {{ __('Checklist') }}
    </div>
    <div class="mb-2 text-sm text-ink-gray-5">
      {{
        __(
          'Copies of the data outside the CRM. Every item must be ticked before the request can be closed.',
        )
      }}
    </div>
    <div v-if="!rows.length" class="text-base text-ink-gray-5">
      {{ __('No checklist items.') }}
    </div>
    <div
      v-for="row in rows"
      :key="row.name"
      class="flex items-center gap-3 border-b py-2 text-base text-ink-gray-8"
    >
      <FormControl
        type="checkbox"
        :modelValue="Boolean(row.done)"
        :disabled="!editable || saving"
        @change="(e) => toggle(row, e.target.checked)"
      />
      <span class="min-w-0 flex-1" :class="{ 'text-ink-gray-5': row.done }">
        {{ row.description }}
      </span>
      <span v-if="row.done && row.done_by" class="text-sm text-ink-gray-5">
        {{ __('{0} on {1}', [doneBy(row), doneOn(row)]) }}
      </span>
    </div>
    <div v-if="editable" class="mt-3 flex items-end gap-2">
      <FormControl
        v-model="newItem"
        class="flex-1"
        type="text"
        :placeholder="
          __('Add an item, for example a provider that holds a copy')
        "
        @keydown.enter="add"
      />
      <Button
        :label="__('Add')"
        :disabled="!newItem.trim() || saving"
        @click="add"
      />
    </div>
    <ErrorMessage class="mt-2" :message="error" />
  </section>
</template>

<script setup>
import { formatDate } from '@/utils'
import { usersStore } from '@/stores/users'
import { errorText } from '@/utils/erasureRequest'
import { call } from 'frappe-ui'
import { computed, ref } from 'vue'

const props = defineProps({
  // the request, as the page loaded it
  request: { type: Object, required: true },
  // Compliance only; the server refuses everyone else
  editable: { type: Boolean, default: false },
})

// `refresh` fires after every change, so the page shows who ticked what.
const emit = defineEmits(['refresh'])

const { getUser } = usersStore()
const saving = ref(false)
const error = ref('')
const newItem = ref('')

const rows = computed(() => props.request.checklist || [])

const doneBy = (row) => getUser(row.done_by).full_name
const doneOn = (row) => formatDate(row.done_on, 'MMM D, YYYY')

// A checklist is a plain edit of the request: the server stamps who ticked an
// item and when, so the saved rows go back as they are, with only the change.
async function save(nextRows) {
  saving.value = true
  error.value = ''
  try {
    await call('frappe.client.set_value', {
      doctype: 'CRM Erasure Request',
      name: props.request.name,
      fieldname: { checklist: nextRows },
    })
  } catch (e) {
    error.value = errorText(e)
  } finally {
    saving.value = false
    emit('refresh')
  }
}

function toggle(row, done) {
  save(
    rows.value.map((item) =>
      item === row ? { ...item, done: done ? 1 : 0 } : item,
    ),
  )
}

async function add() {
  const description = newItem.value.trim()
  if (!description) return
  await save([...rows.value, { description, done: 0 }])
  if (!error.value) newItem.value = ''
}
</script>
