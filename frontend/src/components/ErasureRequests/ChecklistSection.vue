<template>
  <section class="flex flex-col gap-3 rounded-lg border p-4">
    <div>
      <h3 class="text-lg-medium text-ink-gray-9">{{ __('Checklist') }}</h3>
      <p class="text-p-sm text-ink-gray-6">
        {{
          __(
            'Copies of the data outside the CRM, for example call recordings at the telephony provider. The request cannot close while an item is open.',
          )
        }}
      </p>
    </div>
    <p v-if="!request.checklist?.length" class="text-p-sm text-ink-gray-5">
      {{ __('No checklist items') }}
    </p>
    <div v-else class="divide-y text-base">
      <div
        v-for="item in request.checklist"
        :key="item.name"
        class="flex items-start gap-3 py-2"
      >
        <Checkbox
          class="mt-0.5"
          :model-value="Boolean(item.done)"
          :disabled="!request.can?.manage_checklist"
          @update:model-value="(value) => setDone(item, value)"
        />
        <div class="min-w-0 flex-1">
          <div class="text-ink-gray-8" :class="item.done && 'line-through'">
            {{ item.description }}
          </div>
          <div v-if="item.done" class="text-p-sm text-ink-gray-5">
            {{
              __('Done by {0} on {1}', [
                getUser(item.done_by).full_name,
                formatDate(item.done_on),
              ])
            }}
          </div>
          <div v-else-if="item.auto_added" class="text-p-sm text-ink-gray-5">
            {{ __('Added by the erasure') }}
          </div>
        </div>
      </div>
    </div>
    <div v-if="request.can?.manage_checklist" class="flex gap-2">
      <FormControl
        v-model="description"
        class="flex-1"
        type="text"
        :placeholder="__('Describe a copy held outside the CRM')"
        @keydown.enter="add"
      />
      <Button
        :label="__('Add item')"
        :loading="adding"
        :disabled="!description.trim()"
        @click="add"
      />
    </div>
  </section>
</template>

<script setup>
import { runAction } from '@/components/ErasureRequests/erasureApi'
import { usersStore } from '@/stores/users'
import { formatDate } from '@/utils'
import { Checkbox, FormControl } from 'frappe-ui'
import { ref } from 'vue'

const props = defineProps({
  request: { type: Object, required: true },
})
const emit = defineEmits(['updated'])

const { getUser } = usersStore()
const description = ref('')
const adding = ref(false)

async function setDone(item, done) {
  const result = await runAction('review.set_checklist_item_done', {
    name: props.request.name,
    row: item.name,
    done,
  })
  if (result) emit('updated', result)
}

async function add() {
  if (!description.value.trim()) return
  adding.value = true
  const result = await runAction('review.add_checklist_item', {
    name: props.request.name,
    description: description.value.trim(),
  })
  adding.value = false
  if (!result) return
  description.value = ''
  emit('updated', result)
}
</script>
