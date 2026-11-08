<template>
  <Dialog
    v-model:open="open"
    :title="__('Approve {0}', [requestName])"
    size="2xl"
  >
    <template #default>
      <div class="flex flex-col gap-4">
        <div
          v-if="loading"
          class="flex items-center justify-center py-8 text-ink-gray-5"
        >
          <LoadingIndicator class="h-5 w-5" />
        </div>
        <ErrorMessage v-else-if="loadError" :message="loadError" />

        <template v-else-if="preview">
          <section class="flex flex-col gap-2">
            <h4 class="text-base-semibold text-ink-gray-9">
              {{ __('Will be removed') }}
            </h4>
            <ul class="divide-y rounded border">
              <li
                v-for="row in preview.remove"
                :key="row.kind"
                class="flex items-start justify-between gap-3 px-3 py-2 text-base"
                :class="row.count ? 'text-ink-gray-8' : 'text-ink-gray-5'"
              >
                <div class="min-w-0">
                  <div>{{ __(row.kind) }}</div>
                  <ul
                    v-if="row.links?.length"
                    class="mt-1 flex flex-col gap-0.5 text-sm"
                  >
                    <li
                      v-for="link in row.links"
                      :key="link.doctype + link.name"
                    >
                      <router-link
                        v-if="matchRoute(link.doctype, link.name)"
                        :to="matchRoute(link.doctype, link.name)"
                        target="_blank"
                        class="text-ink-gray-6 underline hover:text-ink-gray-9"
                      >
                        {{ link.title || link.name }}
                      </router-link>
                      <span v-else class="text-ink-gray-6">
                        {{ link.title || link.name }}
                      </span>
                    </li>
                  </ul>
                </div>
                <div class="shrink-0 tabular-nums">{{ row.count }}</div>
              </li>
            </ul>
          </section>

          <section class="flex flex-col gap-2">
            <h4 class="text-base-semibold text-ink-gray-9">
              {{ __('Will be kept') }}
            </h4>
            <ul class="divide-y rounded border">
              <li
                v-for="row in preview.keep"
                :key="row.label"
                class="px-3 py-2 text-base text-ink-gray-8"
              >
                <div>{{ __(row.label) }}</div>
                <ul
                  v-if="row.links?.length"
                  class="mt-1 flex flex-col gap-0.5 text-sm"
                >
                  <li v-for="link in row.links" :key="link.doctype + link.name">
                    <router-link
                      v-if="matchRoute(link.doctype, link.name)"
                      :to="matchRoute(link.doctype, link.name)"
                      target="_blank"
                      class="text-ink-gray-6 underline hover:text-ink-gray-9"
                    >
                      {{ link.title || link.name }}
                    </router-link>
                    <span v-else class="text-ink-gray-6">
                      {{ link.title || link.name }}
                    </span>
                  </li>
                </ul>
              </li>
            </ul>
          </section>

          <section
            v-if="hasWarnings"
            class="flex flex-col gap-2 rounded-4 border border-outline-amber-2 bg-surface-amber-2 p-3 text-sm text-ink-amber-6"
            role="alert"
          >
            <h4 class="text-base-semibold">{{ __('Warnings') }}</h4>
            <div v-if="openChecklist.length">
              <div class="font-medium">
                {{ __('Checklist items still open') }}
              </div>
              <ul class="list-disc pl-5">
                <li v-for="item in openChecklist" :key="item">{{ item }}</li>
              </ul>
            </div>
            <div v-if="unlistedFields.length">
              <div class="font-medium">
                {{ __('Custom fields not on the personal fields list') }}
              </div>
              <ul class="list-disc pl-5">
                <li
                  v-for="field in unlistedFields"
                  :key="field.dt + field.fieldname"
                >
                  {{ field.label || field.fieldname }} ({{ field.dt }}:
                  {{ field.fieldname }})
                </li>
              </ul>
            </div>
          </section>

          <div class="flex flex-col gap-2">
            <p class="text-base-semibold text-ink-red-4">
              {{ __("This can't be undone.") }}
            </p>
            <FormControl
              v-model="typed"
              type="text"
              autocomplete="off"
              :label="__('Type {0} to confirm', [requestName])"
              @keydown.enter.prevent="approve"
            />
          </div>
        </template>
      </div>
    </template>
    <template #actions>
      <div class="flex justify-end gap-2">
        <Button variant="subtle" :label="__('Cancel')" @click="open = false" />
        <Button
          variant="solid"
          theme="red"
          :label="__('Erase permanently')"
          :loading="approving"
          :disabled="!canErase"
          @click="approve"
        />
      </div>
    </template>
  </Dialog>
</template>

<script setup>
import { confirmationMatches, matchRoute } from '@/utils/erasureRequest'
import { Dialog, LoadingIndicator, call, toast } from 'frappe-ui'
import { computed, ref, watch } from 'vue'

const props = defineProps({
  requestName: { type: String, required: true },
})
const emit = defineEmits(['approved'])

const open = defineModel({ type: Boolean, default: false })

const preview = ref(null)
const loading = ref(false)
const loadError = ref('')
const typed = ref('')
const approving = ref(false)

const openChecklist = computed(
  () => preview.value?.warnings?.open_checklist || [],
)
const unlistedFields = computed(
  () => preview.value?.warnings?.unlisted_custom_fields || [],
)
const hasWarnings = computed(
  () => openChecklist.value.length > 0 || unlistedFields.value.length > 0,
)
const canErase = computed(
  () =>
    !!preview.value &&
    !approving.value &&
    confirmationMatches(typed.value, props.requestName),
)

function errorText(error, fallback) {
  return error?.messages?.[0] || error?.message || fallback
}

async function loadPreview() {
  loading.value = true
  loadError.value = ''
  preview.value = null
  try {
    preview.value = await call('crm.privacy.api.get_erasure_preview', {
      name: props.requestName,
    })
  } catch (error) {
    loadError.value = errorText(error, __('Could not load the preview'))
    toast.error(loadError.value)
  } finally {
    loading.value = false
  }
}

watch(open, (value) => {
  if (!value) return
  typed.value = ''
  loadPreview()
})

async function approve() {
  if (!canErase.value) return
  approving.value = true
  try {
    const result = await call('crm.privacy.api.approve_request', {
      name: props.requestName,
      confirmation: typed.value.trim(),
    })
    open.value = false
    if (result?.doc?.status === 'On Hold') {
      toast.warning(
        __('The person is still on an open deal; the request is on hold.'),
      )
    }
    emit('approved', result)
  } catch (error) {
    toast.error(errorText(error, __('Could not approve this request')))
  } finally {
    approving.value = false
  }
}
</script>
