<script setup lang="ts">
import { inject, useId } from 'vue'
import { RadioGroupItem } from '../radio-group'
import { Label } from '../label'
import { encodeChoice } from './context'
import { radioContextKey } from './selectionContext'
defineProps<{ value?: unknown; label?: string | number; disabled?: boolean; button?: boolean }>()
const context = inject(radioContextKey, undefined)
const id = `radio-${useId()}`
</script>
<template>
  <span class="radio-choice" :class="{ 'radio-choice--button': button, 'is-selected': Object.is(context?.value.value, value ?? label), 'is-disabled': disabled || context?.disabled.value }">
    <RadioGroupItem :id="id" :value="encodeChoice(value ?? label)" :disabled="disabled || context?.disabled.value" />
    <Label :for="id"><slot>{{ label }}</slot></Label>
  </span>
</template>
