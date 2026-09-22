<script setup lang="ts">
defineOptions({ name: 'ChoiceOption' })
defineProps<{ value?: unknown; label?: string | number; disabled?: boolean }>()
</script>
<template><slot /></template>
