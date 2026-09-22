<script setup lang="ts">
import RadioChoice from './RadioChoice.vue'
defineProps<{ value?: unknown; label?: string | number; disabled?: boolean }>()
</script>
<template><RadioChoice :value="value" :label="label" :disabled="disabled" button><slot /></RadioChoice></template>
