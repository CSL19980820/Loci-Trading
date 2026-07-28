<script setup lang="ts">
defineProps<{
  title: string
  subtitle?: string
}>()
</script>

<template>
  <header class="page-header">
    <div class="page-header-title">
      <h1>{{ title }}</h1>
      <span v-if="subtitle" class="page-header-sub">{{ subtitle }}</span>
      <slot name="meta" />
    </div>
    <div class="page-header-actions">
      <slot />
    </div>
  </header>
</template>

<style scoped>
.page-header {
  position: sticky;
  top: 0;
  z-index: 6;
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 0.75rem;
  margin: -0.75rem -1rem 0.65rem;
  padding: 0.75rem 1rem 0.55rem;
  min-height: 2.25rem;
  background: var(--paper);
  box-shadow: 0 1px 0 var(--rule);
}

.page-header-title {
  display: flex;
  align-items: baseline;
  flex-wrap: wrap;
  gap: 0.45rem 0.75rem;
  min-width: 0;
}

.page-header-title h1 {
  margin: 0;
  font-size: 1.35rem;
  font-weight: 700;
  letter-spacing: -0.02em;
  line-height: 1.2;
  color: var(--ink);
}

.page-header-sub {
  color: var(--mist);
  font-family: var(--mono);
  font-size: 0.85rem;
}

.page-header-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.5rem;
}

@media (max-width: 640px) {
  .page-header {
    margin: -0.65rem -0.75rem 0.55rem;
    padding: 0.65rem 0.75rem 0.5rem;
  }
}
</style>
