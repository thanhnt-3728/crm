<template>
  <div class="flex flex-col gap-3">
    <p v-if="!members.length" class="text-p-sm text-ink-gray-5">
      {{ __('No Compliance members yet') }}
    </p>
    <div v-else class="divide-y">
      <div
        v-for="member in members"
        :key="member.user"
        class="flex items-center gap-3 py-2"
      >
        <div class="min-w-0 flex-1">
          <div class="truncate text-p-base text-ink-gray-8">
            {{ member.full_name || member.user }}
          </div>
          <div class="truncate text-p-sm text-ink-gray-5">
            {{ member.user
            }}<template v-if="!member.enabled">
              · {{ __('Disabled') }}</template
            >
          </div>
        </div>
        <Button
          v-if="member.user !== session.user"
          :label="__('Remove')"
          :loading="busy === member.user"
          @click="change(member.user, false)"
        />
      </div>
    </div>
    <div class="flex items-end gap-2">
      <Link
        v-model="newUser"
        class="flex-1"
        doctype="User"
        :label="__('Add a member')"
        :filters="{ enabled: 1, user_type: 'System User' }"
        hide-me
      />
      <Button
        :label="__('Add')"
        :loading="busy === newUser"
        :disabled="!newUser"
        @click="change(newUser, true)"
      />
    </div>
    <p class="text-p-sm text-ink-gray-5">
      {{
        __(
          'Only Compliance members can approve, decline, manage the checklist and close requests. You cannot change your own membership. Each change is recorded.',
        )
      }}
    </p>
  </div>
</template>

<script setup>
import Link from '@/components/Controls/Link.vue'
import { runAction } from '@/components/ErasureRequests/erasureApi'
import { sessionStore } from '@/stores/session'
import { toast } from 'frappe-ui'
import { ref } from 'vue'

const members = defineModel({ type: Array, required: true })

const session = sessionStore()
const newUser = ref('')
const busy = ref('')

async function change(user, enabled) {
  busy.value = user
  const result = await runAction('review.set_compliance_member', {
    user,
    enabled,
  })
  busy.value = ''
  if (!result) return
  members.value = result
  if (enabled) newUser.value = ''
  toast.success(
    enabled
      ? __('{0} is now a Compliance member', [user])
      : __('{0} is no longer a Compliance member', [user]),
  )
}
</script>
