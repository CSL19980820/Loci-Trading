<script setup lang="ts">
import { Skeleton } from '@/shared/components/ui/skeleton'
withDefaults(defineProps<{ label?: string }>(), { label: '读取工作区…' })
</script>
<template>
  <div class="workspace-loading" role="status" aria-live="polite" :aria-label="label">
    <span class="sr-only">{{ label }}</span>
    <div class="workspace-loading__head"><Skeleton class="h-7 w-36" /><Skeleton class="h-7 w-24" /></div>
    <div class="workspace-loading__stats"><Skeleton v-for="i in 4" :key="i" class="h-12" /></div>
    <div class="workspace-loading__body"><Skeleton v-for="i in 6" :key="i" class="h-9 w-full" /></div>
  </div>
</template>
<style scoped>
.workspace-loading { display:flex; flex-direction:column; gap:14px; flex:1; min-width:0; min-height:0; padding:12px 0; overflow:hidden; }
.workspace-loading__head { display:flex; justify-content:space-between; align-items:center; }
.workspace-loading__stats { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:10px; }
.workspace-loading__body { display:grid; gap:10px; padding:14px; border:1px solid var(--border-subtle); border-radius:var(--radius-lg); background:var(--surface); }
@media(max-width:640px) { .workspace-loading__stats { grid-template-columns:repeat(2,minmax(0,1fr)); } }
@media(prefers-reduced-motion:reduce) { .workspace-loading :deep(*) { animation:none; } }
</style>
