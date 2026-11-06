<template>
  <Button
    v-if="actions.submit"
    variant="solid"
    :label="__('Submit for approval')"
    @click="emit('submit')"
  />
  <Button
    v-if="actions.approve"
    variant="solid"
    :label="__('Approve')"
    @click="emit('approve')"
  />
  <Button
    v-if="actions.reject"
    theme="red"
    :label="__('Reject')"
    @click="emit('reject')"
  />
  <Button v-if="actions.close" :label="__('Close')" @click="emit('close')" />
  <Button v-if="actions.retry" :label="__('Retry')" @click="emit('retry')" />
</template>

<script setup>
import { Button } from 'frappe-ui'

// `actions` comes from availableActions(); the page decides what each click does.
defineProps({ actions: { type: Object, required: true } })
const emit = defineEmits(['submit', 'approve', 'reject', 'close', 'retry'])
</script>
