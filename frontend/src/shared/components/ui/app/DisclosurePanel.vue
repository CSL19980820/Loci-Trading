<script setup lang="ts">
import { useId } from 'vue'
import { AccordionItem, AccordionTrigger, AccordionContent } from '../accordion'
import { encodeChoice } from './context'
defineProps<{ name?: string | number; title?: string; disabled?: boolean }>()
const id = useId()
</script>
<template><AccordionItem :value="encodeChoice(name ?? id)" :disabled="disabled"><AccordionTrigger><slot name="title">{{ title }}</slot></AccordionTrigger><AccordionContent><slot /></AccordionContent></AccordionItem></template>
