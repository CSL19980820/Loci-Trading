<script setup lang="ts">
import TradingReportDocument from '@/shared/components/TradingReportDocument.vue'
import type { GuardianReportSection } from '@/shared/types/guardian'
defineProps<{ sections: GuardianReportSection[]; period?: string; title?: string; metadata?: string }>()
</script>
<template><TradingReportDocument :sections="sections" :title="title" :metadata="metadata" /></template>
