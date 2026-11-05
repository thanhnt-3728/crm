<template>
  <LayoutHeader>
    <template #left-header>
      <Breadcrumbs :items="breadcrumbs" />
    </template>
    <template #right-header>
      <Button
        v-if="canSubmit"
        variant="solid"
        :label="__('Submit to Compliance')"
        :loading="submitting"
        @click="submitRequest"
      />
      <Button
        v-if="canDecide"
        theme="red"
        :label="__('Decline')"
        @click="showDecline = true"
      />
      <Button
        v-if="canDecide"
        variant="solid"
        :label="__('Approve')"
        @click="showApprove = true"
      />
      <Button
        v-if="canClose"
        variant="solid"
        :label="__('Close request')"
        @click="showClose = true"
      />
      <Button
        v-if="canReset"
        :label="__('Reset stuck erasure')"
        :loading="resetting"
        @click="resetStuck"
      />
    </template>
  </LayoutHeader>

  <div v-if="request.error" class="p-5">
    <ErrorMessage :message="errorText(request.error)" />
  </div>
  <div v-else-if="!doc" class="p-5 text-ink-gray-5">
    {{ __('Loading...') }}
  </div>
  <div v-else class="flex-1 overflow-y-auto">
    <div class="mx-auto flex max-w-4xl flex-col gap-6 p-5">
      <!-- header -->
      <div class="flex flex-col gap-3">
        <div class="flex flex-wrap items-center gap-3">
          <h1 class="text-3xl-medium text-ink-gray-9">{{ doc.name }}</h1>
          <Badge :label="__(doc.status)" :theme="statusTheme(doc.status)" />
          <Badge
            v-if="doc.status !== 'Closed'"
            :label="daysLeftLabel(doc.days_left)"
            :theme="urgencyTheme(doc.days_left)"
          />
        </div>
        <div class="flex flex-wrap items-center gap-x-8 gap-y-2 text-base">
          <div>
            <div class="text-sm text-ink-gray-5">
              {{ __('Acknowledge by') }}
            </div>
            <div class="text-ink-gray-9">{{ date(doc.acknowledge_by) }}</div>
          </div>
          <div>
            <div class="text-sm text-ink-gray-5">{{ __('Respond by') }}</div>
            <div class="text-ink-gray-9">{{ date(doc.respond_by) }}</div>
          </div>
          <div>
            <div class="text-sm text-ink-gray-5">{{ __('Received') }}</div>
            <div class="text-ink-gray-9">{{ date(doc.received_on) }}</div>
          </div>
          <div v-if="!restricted && isCompliance() && doc.status !== 'Closed'">
            <FormControl
              type="checkbox"
              :label="__('Acknowledgment sent')"
              :modelValue="Boolean(doc.acknowledgment_sent)"
              :disabled="saving"
              @change="(e) => setAcknowledged(e.target.checked)"
            />
            <div
              v-if="doc.acknowledgment_sent && doc.acknowledged_on"
              class="mt-0.5 text-sm text-ink-gray-5"
            >
              {{ __('Sent on {0}', [date(doc.acknowledged_on)]) }}
            </div>
          </div>
          <div v-else-if="!restricted && doc.acknowledgment_sent">
            <div class="text-sm text-ink-gray-5">
              {{ __('Acknowledgment sent') }}
            </div>
            <div class="text-ink-gray-9">{{ date(doc.acknowledged_on) }}</div>
          </div>
        </div>
      </div>

      <ErrorMessage :message="actionError" />

      <div
        v-if="doc.erasure_error"
        class="rounded-md bg-surface-red-2 p-3 text-base text-ink-red-4"
        role="alert"
      >
        <div class="font-medium">{{ __('The erasure failed') }}</div>
        <div class="whitespace-pre-line">{{ doc.erasure_error }}</div>
      </div>

      <div
        v-if="canReset"
        class="rounded-md bg-surface-amber-2 p-3 text-base text-ink-amber-7"
      >
        {{
          __(
            'The erasure job has not finished an hour after approval. Reset the request to put it back for sign-off; nothing was erased.',
          )
        }}
      </div>

      <div
        v-if="doc.status === 'On Hold'"
        class="rounded-md bg-surface-amber-2 p-3 text-base text-ink-amber-7"
      >
        <div class="font-medium">{{ __('On hold') }}</div>
        <div>
          {{
            __(
              'The person is a contact on an open deal. Remove them from the deal or close it, then this request returns to sign-off.',
            )
          }}
        </div>
        <ul v-if="holdDeals.length" class="mt-1 list-disc pl-5">
          <li v-for="deal in holdDeals" :key="deal">
            <router-link
              :to="{ name: 'Deal', params: { dealId: deal } }"
              target="_blank"
              class="underline"
            >
              {{ deal }}
            </router-link>
          </li>
        </ul>
      </div>

      <div
        v-if="restricted"
        class="rounded-md bg-surface-gray-2 p-3 text-base text-ink-gray-7"
      >
        {{
          __(
            'This request is with Compliance. Only its status and due dates are shown here.',
          )
        }}
      </div>

      <template v-else>
        <!-- requester -->
        <section v-if="doc.status !== 'Closed'" class="flex flex-col gap-3">
          <div class="text-lg-medium text-ink-gray-9">
            {{ __('Requester details') }}
          </div>
          <div class="grid grid-cols-1 gap-3 text-base sm:grid-cols-3">
            <div>
              <div class="text-sm text-ink-gray-5">
                {{ __('How it arrived') }}
              </div>
              <div class="text-ink-gray-9">{{ __(doc.channel) }}</div>
            </div>
            <div class="sm:col-span-2">
              <div class="text-sm text-ink-gray-5">{{ __('Names') }}</div>
              <div class="whitespace-pre-line text-ink-gray-9">
                {{ doc.requester_names || '-' }}
              </div>
            </div>
          </div>
          <div class="text-base">
            <div class="text-sm text-ink-gray-5">
              {{ __('Original message') }}
            </div>
            <div class="whitespace-pre-line text-ink-gray-9">
              {{ doc.original_message || '-' }}
            </div>
          </div>
        </section>

        <ErasureMatchesSection
          v-if="doc.status !== 'Closed'"
          :request="doc"
          :editable="canEditMatches"
          @refresh="reload"
        />

        <section
          v-if="doc.status !== 'Closed' && canSeeEmails"
          class="flex flex-col gap-2"
        >
          <div class="text-lg-medium text-ink-gray-9">
            {{ __('Emails from the requester') }}
          </div>
          <div v-if="!emails.data?.length" class="text-base text-ink-gray-5">
            {{
              emails.loading
                ? __('Loading...')
                : __('No emails have arrived for this request.')
            }}
          </div>
          <ul v-else class="divide-y text-base">
            <li
              v-for="email in emails.data"
              :key="email.name"
              class="flex items-center justify-between gap-3 py-1.5"
            >
              <span class="truncate text-ink-gray-9">
                {{ email.subject || __('(no subject)') }}
              </span>
              <span class="shrink-0 text-sm text-ink-gray-5">
                {{ date(email.communication_date) }}
              </span>
            </li>
          </ul>
        </section>

        <ErasureChecklistSection
          v-if="
            doc.status !== 'Closed' && (isCompliance() || doc.checklist?.length)
          "
          :request="doc"
          :editable="isCompliance()"
          @refresh="reload"
        />

        <section
          v-if="
            doc.status !== 'Closed' &&
            (isCompliance() || doc.contract_references)
          "
        >
          <div class="mb-1 text-lg-medium text-ink-gray-9">
            {{ __('Contract references') }}
          </div>
          <div class="mb-2 text-sm text-ink-gray-5">
            {{
              __(
                'Signed contracts or orders that must be kept, one per line. They are kept with the log entry and not erased.',
              )
            }}
          </div>
          <FormControl
            v-if="isCompliance()"
            v-model="contractReferences"
            type="textarea"
            :rows="3"
            :disabled="saving"
            @blur="saveContractReferences"
          />
          <div v-else class="whitespace-pre-line text-base text-ink-gray-9">
            {{ doc.contract_references }}
          </div>
        </section>

        <!-- outcome -->
        <section
          v-if="doc.answered_on || doc.outcome || doc.denial_reason"
          class="text-base"
        >
          <div class="mb-2 text-lg-medium text-ink-gray-9">
            {{ __('Outcome') }}
          </div>
          <div class="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <div>
              <div class="text-sm text-ink-gray-5">
                {{ __('Date answered') }}
              </div>
              <div class="text-ink-gray-9">{{ date(doc.answered_on) }}</div>
            </div>
            <div>
              <div class="text-sm text-ink-gray-5">{{ __('Outcome') }}</div>
              <div class="text-ink-gray-9">{{ __(doc.outcome) }}</div>
            </div>
            <div v-if="doc.delete_after">
              <div class="text-sm text-ink-gray-5">{{ __('Kept until') }}</div>
              <div class="text-ink-gray-9">{{ date(doc.delete_after) }}</div>
            </div>
          </div>
          <div v-if="doc.denial_reason" class="mt-3">
            <div class="text-sm text-ink-gray-5">{{ __('Denial reason') }}</div>
            <div class="whitespace-pre-line text-ink-gray-9">
              {{ doc.denial_reason }}
            </div>
          </div>
        </section>
      </template>
    </div>
  </div>

  <ApproveErasureModal
    v-if="doc"
    v-model="showApprove"
    :request="doc.name"
    @approved="reload"
    @refresh="reload"
  />
  <DeclineErasureModal
    v-if="doc"
    v-model="showDecline"
    :request="doc.name"
    @refresh="reload"
  />
  <CloseErasureModal
    v-if="doc && !restricted"
    v-model="showClose"
    :request="doc"
    @refresh="reload"
  />
</template>

<script setup>
import LayoutHeader from '@/components/LayoutHeader.vue'
import ErasureChecklistSection from '@/components/Privacy/ErasureChecklistSection.vue'
import ErasureMatchesSection from '@/components/Privacy/ErasureMatchesSection.vue'
import ApproveErasureModal from '@/components/Modals/ApproveErasureModal.vue'
import CloseErasureModal from '@/components/Modals/CloseErasureModal.vue'
import DeclineErasureModal from '@/components/Modals/DeclineErasureModal.vue'
import { sessionStore } from '@/stores/session'
import { usersStore } from '@/stores/users'
import { formatDate } from '@/utils'
import {
  canApprove,
  canResetStuck,
  daysLeftLabel,
  errorText,
  statusTheme,
  urgencyTheme,
} from '@/utils/erasureRequest'
import { Breadcrumbs, call, createResource, dayjs, toast } from 'frappe-ui'
import { computed, ref, watch } from 'vue'

const props = defineProps({
  requestId: { type: String, required: true },
})

const { user } = sessionStore()
const { isCompliance, isManager } = usersStore()

const showApprove = ref(false)
const showDecline = ref(false)
const showClose = ref(false)
const submitting = ref(false)
const saving = ref(false)
const actionError = ref('')
const holdDeals = ref([])
const contractReferences = ref('')
const resetting = ref(false)

const request = createResource({
  url: 'crm.api.erasure.get_request',
  makeParams: () => ({ name: props.requestId }),
  auto: true,
  onSuccess(data) {
    contractReferences.value = data.contract_references || ''
    loadHoldDeals(data)
    loadEmails(data)
  },
})

// Inbound mail attached to the request, for Compliance and Sales Managers.
const emails = createResource({
  url: 'crm.api.erasure.linked_emails',
  makeParams: () => ({ name: props.requestId }),
})

const doc = computed(() => request.data)

watch(
  () => props.requestId,
  () => request.reload(),
)

function reload() {
  return request.reload()
}

// After submit the logger gets only the header fields, never the details.
const restricted = computed(() => Boolean(doc.value) && !doc.value.doctype)

const isLogger = computed(() => doc.value?.logged_by === user)
const canSubmit = computed(
  () =>
    !restricted.value &&
    doc.value?.status === 'Logged' &&
    (isLogger.value || isCompliance()),
)
const canDecide = computed(
  () => !restricted.value && canApprove(doc.value, user, isCompliance()),
)
const canClose = computed(
  () =>
    !restricted.value &&
    isCompliance() &&
    ['Erased', 'Declined'].includes(doc.value?.status),
)
const canReset = computed(
  () => !restricted.value && canResetStuck(doc.value, isCompliance()),
)
const canSeeEmails = computed(() => isCompliance() || isManager())
const canEditMatches = computed(
  () =>
    !restricted.value &&
    ((isLogger.value && doc.value.status === 'Logged') ||
      (isCompliance() &&
        ['Logged', 'Awaiting Sign-off', 'On Hold'].includes(doc.value.status))),
)

const breadcrumbs = computed(() => [
  { label: __('Privacy requests'), route: { name: 'ErasureRequests' } },
  {
    label: props.requestId,
    route: { name: 'ErasureRequest', params: { requestId: props.requestId } },
  },
])

function date(value) {
  return value ? formatDate(value, 'MMM D, YYYY') : ''
}

// Only Compliance and Sales Managers may ask; the server refuses the rest.
async function loadHoldDeals(data) {
  holdDeals.value = []
  if (data.status !== 'On Hold' || !data.doctype) return
  if (!isCompliance() && !isManager()) return
  try {
    holdDeals.value = await call('crm.api.erasure.open_deals', {
      name: data.name,
    })
  } catch {
    // the banner still explains the hold without the list
  }
}

function loadEmails(data) {
  if (!data.doctype || data.status === 'Closed' || !canSeeEmails.value) return
  emails.reload()
}

async function resetStuck() {
  resetting.value = true
  actionError.value = ''
  try {
    await call('crm.api.erasure.reset_stuck', { name: doc.value.name })
    toast.success(__('The request is back for sign-off'))
  } catch (e) {
    actionError.value = errorText(e)
  } finally {
    resetting.value = false
    reload()
  }
}

async function submitRequest() {
  submitting.value = true
  actionError.value = ''
  try {
    await call('crm.api.erasure.submit', { name: doc.value.name })
    toast.success(__('Submitted to Compliance'))
  } catch (e) {
    actionError.value = errorText(e)
  } finally {
    submitting.value = false
    reload()
  }
}

// The server refuses any edit from someone who may not make it.
async function setValues(values) {
  saving.value = true
  actionError.value = ''
  try {
    await call('frappe.client.set_value', {
      doctype: 'CRM Erasure Request',
      name: doc.value.name,
      fieldname: values,
    })
  } catch (e) {
    actionError.value = errorText(e)
  } finally {
    saving.value = false
    reload()
  }
}

function setAcknowledged(sent) {
  return setValues({
    acknowledgment_sent: sent ? 1 : 0,
    acknowledged_on: sent ? dayjs().format('YYYY-MM-DD') : null,
  })
}

function saveContractReferences() {
  if (contractReferences.value === (doc.value.contract_references || '')) return
  return setValues({ contract_references: contractReferences.value })
}
</script>
