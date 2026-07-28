<script setup lang="ts">
withDefaults(
  defineProps<{
    busy?: boolean
    label?: string
    /** 盖住父级时父级需 position:relative */
    overlay?: boolean
  }>(),
  {
    busy: false,
    label: '加载中…',
    overlay: false,
  },
)
</script>

<template>
  <div v-if="busy" class="page-busy" :class="{ 'page-busy--overlay': overlay }" role="status">
    <span class="page-busy-spin" aria-hidden="true" />
    <span class="page-busy-label">{{ label }}</span>
  </div>
</template>

<style scoped>
.page-busy {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 0.65rem;
  min-height: 8rem;
  padding: 1.25rem;
  color: var(--mist);
  font-size: 0.85rem;
}

.page-busy--overlay {
  position: absolute;
  inset: 0;
  z-index: 5;
  min-height: 0;
  background: color-mix(in srgb, var(--sheet) 78%, transparent);
  backdrop-filter: blur(1px);
}

.page-busy-spin {
  width: 1.35rem;
  height: 1.35rem;
  border: 2px solid var(--rule);
  border-top-color: var(--seal);
  border-radius: 50%;
  animation: page-busy-rot 0.7s linear infinite;
}

.page-busy-label {
  letter-spacing: 0.04em;
}

@keyframes page-busy-rot {
  to {
    transform: rotate(360deg);
  }
}

@media (prefers-reduced-motion: reduce) {
  .page-busy-spin {
    animation: none;
    border-top-color: var(--seal);
    opacity: 0.7;
  }
}
</style>
