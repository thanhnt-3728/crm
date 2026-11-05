<template>
  <Dialog
    v-model:open="show"
    :title="__('Approve erasure of {0}', [request])"
    size="2xl"
    @close="close"
  >
    <template #default>
      <div v-if="preview.loading" class="py-8 text-center text-ink-gray-5">
        {{ __('Working out what will be erased...') }}
      </div>
      <ErrorMessage
        v-else-if="preview.error"
        :message="errorText(preview.error)"
      />
      <div
        v-else-if="data"
        class="flex flex-col gap-5 text-base text-ink-gray-8"
      >
        <section>
          <div class="mb-2 text-lg-medium text-ink-gray-9">
            {{ __('Will be removed') }}
          </div>
          <div v-if="!removedKinds.length" class="text-ink-gray-5">
            {{ __('Nothing. No records are confirmed for this request.') }}
          </div>
          <div v-for="kind in removedKinds" :key="kind" class="border-b py-1.5">
            <button
              type="button"
              class="flex w-full items-center justify-between text-left"
              :aria-expanded="Boolean(expanded[kind])"
              @click="expanded[kind] = !expanded[kind]"
            >
              <span>{{ __(kind) }}</span>
              <span class="flex items-center gap-1 text-ink-gray-6">
                {{ data.counts[kind] }}
                <span
                  :class="
                    expanded[kind] ? 'lucide-chevron-up' : 'lucide-chevron-down'
                  "
                  class="size-4"
                />
              </span>
            </button>
            <ul v-if="expanded[kind]" class="mb-1 mt-1 space-y-1 pl-3 text-sm">
              <li v-for="item in itemsOf(kind)" :key="item.doctype + item.name">
                <router-link
                  v-if="recordRoute(item.doctype, item.name)"
                  :to="recordRoute(item.doctype, item.name)"
                  target="_blank"
                  class="text-ink-gray-7 underline"
                >
                  {{ item.label || item.name }}
                </router-link>
                <span v-else class="text-ink-gray-7">
                  {{ item.label || item.name }}
                </span>
              </li>
            </ul>
          </div>
        </section>

        <section>
          <div class="mb-2 text-lg-medium text-ink-gray-9">
            {{ __('Will be kept') }}
          </div>
          <div v-if="!data.keep.length" class="text-ink-gray-5">
            {{ __('Nothing.') }}
          </div>
          <ul v-else class="space-y-1.5">
            <li v-for="item in data.keep" :key="item.label">
              <span class="text-ink-gray-9">{{ item.label }}</span>
              <span class="text-ink-gray-5"> &mdash; {{ item.reason }}</span>
            </li>
          </ul>
        </section>

        <section
          v-if="
            data.open_checklist.length ||
            data.unlisted_custom_fields.length ||
            unconfirmed.length
          "
          class="rounded-md bg-surface-amber-2 p-3"
        >
          <div class="mb-2 text-lg-medium text-ink-amber-7">
            {{ __('Needs attention') }}
          </div>
          <div v-if="data.open_checklist.length" class="mb-2">
            <div class="text-sm text-ink-gray-7">
              {{ __('Open checklist items') }}
            </div>
            <ul class="list-disc pl-5">
              <li v-for="item in data.open_checklist" :key="item">
                {{ item }}
              </li>
            </ul>
          </div>
          <div v-if="unconfirmed.length" class="mb-2">
            <div class="text-sm text-ink-gray-7">
              {{
                __(
                  'Matches nobody confirmed, records created while the request was open among them. They will not be erased: confirm them on the request first if they are the person.',
                )
              }}
            </div>
            <ul class="list-disc pl-5">
              <li v-for="item in unconfirmed" :key="item.doctype + item.name">
                {{ item.kind }}:
                <router-link
                  v-if="item.route"
                  :to="item.route"
                  target="_blank"
                  class="underline"
                >
                  {{ item.name }}
                </router-link>
                <span v-else>{{ item.name }}</span>
              </li>
            </ul>
          </div>
          <div v-if="data.unlisted_custom_fields.length">
            <div class="text-sm text-ink-gray-7">
              {{
                __(
                  'Custom fields that are not in the personal fields list, so they will not be erased',
                )
              }}
            </div>
            <ul class="list-disc pl-5">
              <li
                v-for="field in data.unlisted_custom_fields"
                :key="field.doctype + field.fieldname"
              >
                {{ field.label || field.fieldname }}
                <span class="text-ink-gray-5">
                  ({{ field.doctype }}.{{ field.fieldname }})
                </span>
              </li>
            </ul>
          </div>
        </section>

        <FormControl
          v-model="typed"
          type="text"
          :label="__('Type {0} to confirm. This can\'t be undone.', [request])"
          :placeholder="request"
          autocomplete="off"
          @keydown.enter="approve"
        />
      </div>
    </template>
    <template #actions>
      <div class="flex items-center justify-between gap-2">
        <div><ErrorMessage :message="error" /></div>
        <div class="flex gap-2">
          <Button :label="__('Cancel')" @click="close" />
          <Button
            variant="solid"
            theme="red"
            :label="__('Approve and erase')"
            :disabled="!canConfirm"
            :loading="approving"
            @click="approve"
          />
        </div>
      </div>
    </template>
  </Dialog>
</template>

<script setup>
import {
  confirmMatches,
  errorText,
  recordRoute,
  unconfirmedMatchItems,
} from '@/utils/erasureRequest'
import { call, createResource, Dialog, toast } from 'frappe-ui'
import { computed, reactive, ref, watch } from 'vue'

const props = defineProps({
  // the request number
  request: { type: String, required: true },
})

// `approved` when the job was queued; `refresh` when the request changed
// without being approved (for example it went On Hold), so the page reloads it.
const emit = defineEmits(['approved', 'refresh'])
const show = defineModel({ type: Boolean })

const typed = ref('')
const error = ref('')
const approving = ref(false)
const expanded = reactive({})

const preview = createResource({
  url: 'crm.api.erasure.preview',
  makeParams: () => ({ name: props.request }),
})
const data = computed(() => preview.data)
const unconfirmed = computed(() =>
  unconfirmedMatchItems(data.value?.unconfirmed_matches),
)

// Each kind that has something to remove, in the order the server lists them.
const removedKinds = computed(() =>
  Object.keys(data.value?.counts || {}).filter(
    (kind) => data.value.counts[kind],
  ),
)

function itemsOf(kind) {
  return data.value.remove.filter((item) => item.kind === kind)
}

const canConfirm = computed(
  () =>
    Boolean(data.value) &&
    !approving.value &&
    confirmMatches(typed.value, props.request),
)

watch(show, (open) => {
  if (!open) return
  typed.value = ''
  error.value = ''
  Object.keys(expanded).forEach((kind) => delete expanded[kind])
  preview.reload()
})

function close() {
  show.value = false
}

async function approve() {
  if (!canConfirm.value) return
  approving.value = true
  error.value = ''
  try {
    await call('crm.api.erasure.approve', {
      name: props.request,
      typed_name: typed.value.trim(),
    })
    toast.success(__('Approved. The erasure is running.'))
    emit('approved')
    close()
  } catch (e) {
    error.value = errorText(e)
    emit('refresh')
  } finally {
    approving.value = false
  }
}
</script>
