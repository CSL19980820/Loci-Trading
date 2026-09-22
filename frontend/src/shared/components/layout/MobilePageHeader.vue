<script setup lang="ts">
defineProps<{ title: string; subtitle?: string }>()
</script>

<template>
  <header class="mobile-heading">
    <div class="mobile-heading__lead">
      <slot name="leading" />
      <div class="mobile-heading__identity">
        <h1>{{ title }}</h1>
        <p v-if="subtitle">{{ subtitle }}</p>
      </div>
    </div>
    <div v-if="$slots.actions" class="mobile-heading__actions"><slot name="actions" /></div>
  </header>
</template>

<style scoped>
.mobile-heading { display:flex; align-items:center; justify-content:space-between; flex:none; gap:10px; min-height:52px; padding:6px 0; }
.mobile-heading__lead { display:flex; align-items:center; gap:8px; min-width:0; }
.mobile-heading__identity { min-width:0; }
.mobile-heading h1 { margin:0; font-size:18px; line-height:1.45; font-weight:650; overflow-wrap:anywhere; }
.mobile-heading p { margin:1px 0 0; color:var(--text-tertiary); font-size:11px; line-height:1.5; overflow-wrap:anywhere; }
.mobile-heading__actions { display:flex; align-items:center; gap:3px; flex:none; }
.mobile-heading__actions :deep(button) { min-height:40px; }
</style>
