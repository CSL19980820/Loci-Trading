<script setup lang="ts">
import { TabsContent } from '../tabs'
import { encodeChoice } from './context'
defineProps<{ name?: string | number; label?: string; disabled?: boolean }>()
</script>
<template><TabsContent class="tab-page" :value="encodeChoice(name)" force-mount><slot /></TabsContent></template>
