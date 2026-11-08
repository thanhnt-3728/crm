<template>
  <LayoutHeader>
    <template #left-header>
      <Breadcrumbs :items="breadcrumbs" />
    </template>
  </LayoutHeader>

  <div
    v-if="email.loading && !email.data"
    class="flex h-full items-center justify-center"
  >
    <LoadingIndicator class="h-6 w-6 text-ink-gray-5" />
  </div>

  <div v-else-if="email.error" class="p-5">
    <ErrorMessage
      :message="email.error?.messages?.[0] || __('This email is not available')"
    />
  </div>

  <div v-else-if="data" class="h-full overflow-y-auto">
    <div class="mx-auto flex max-w-4xl flex-col gap-6 p-5 text-ink-gray-8">
      <p class="text-p-base text-ink-gray-6">
        {{
          __(
            'This email arrived from a person whose data was erased. It is attached to no record. Decide what to do with it.',
          )
        }}
      </p>

      <div class="flex flex-col gap-1">
        <div class="text-2xl-semibold text-ink-gray-9">
          {{ data.subject || __('(no subject)') }}
        </div>
        <div class="text-base text-ink-gray-7">{{ sender }}</div>
        <div class="text-sm text-ink-gray-5">
          {{ formatDate(data.communication_date) }}
        </div>
        <div v-if="data.request" class="text-base text-ink-gray-6">
          {{ __('Erasure request') }}
          <router-link
            :to="{
              name: 'Erasure Request',
              params: { requestId: data.request },
            }"
            class="text-ink-gray-9 underline"
          >
            {{ data.request }}
          </router-link>
        </div>
      </div>

      <!-- External, untrusted HTML: always sanitized. -->
      <!-- eslint-disable vue/no-v-html -->
      <div
        class="prose-f max-w-none rounded border p-4 text-p-base"
        v-html="sanitizeHTML(data.content || '')"
      />
      <!-- eslint-enable vue/no-v-html -->

      <section v-if="data.attachments.length" class="flex flex-col gap-3">
        <h3 class="text-lg-semibold text-ink-gray-9">
          {{ __('Attachments') }}
        </h3>
        <ul class="divide-y rounded border">
          <li
            v-for="file in data.attachments"
            :key="file.name"
            class="flex items-center justify-between gap-3 px-3 py-2 text-base"
          >
            <a
              :href="blockedAttachmentUrl(data.name, file.name)"
              class="truncate text-ink-gray-9 underline"
            >
              {{ file.file_name }}
            </a>
            <span class="shrink-0 text-sm text-ink-gray-5">
              {{ convertSize(file.file_size) }}
            </span>
          </li>
        </ul>
      </section>
    </div>
  </div>
</template>

<script setup>
import LayoutHeader from '@/components/LayoutHeader.vue'
import { convertSize, formatDate, sanitizeHTML } from '@/utils'
import { blockedAttachmentUrl } from '@/utils/erasureRequest'
import { Breadcrumbs, LoadingIndicator, createResource } from 'frappe-ui'
import { computed, watch } from 'vue'

const props = defineProps({
  emailId: { type: String, required: true },
})

// Compliance only, and only for mail from an erased person that is attached to
// nothing. Anyone else gets "This email is not available".
const email = createResource({
  url: 'crm.privacy.api.get_blocked_email',
  makeParams: () => ({ name: props.emailId }),
  auto: true,
})

const data = computed(() => email.data)

const sender = computed(() => {
  const { sender_full_name: name, sender: address } = data.value || {}
  return name && name !== address ? `${name} <${address}>` : address
})

const breadcrumbs = computed(() => [
  {
    label: __('Erasure requests'),
    route: { name: 'Erasure Requests' },
  },
  {
    label: __('Email'),
    route: { name: 'Erasure Email', params: { emailId: props.emailId } },
  },
])

watch(
  () => props.emailId,
  () => email.reload(),
)
</script>
