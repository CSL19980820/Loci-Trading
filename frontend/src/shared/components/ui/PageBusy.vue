<script setup lang="ts">
import { Spinner } from '@/shared/components/ui/spinner'

/**
 * 加载态。
 * - 行内（默认）：一行 32px 的转圈 + 文案，不占版面。
 * - overlay：盖住父级（父级需 position:relative），毛玻璃底 + 居中一枚圆形转圈卡；
 *   延迟 120ms 出现，避免快速请求闪一下。
 */
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
    <span class="page-busy__card">
      <Spinner class="page-busy-spin" aria-hidden="true" />
      <span class="page-busy-label">{{ label }}</span>
    </span>
  </div>
</template>

<style scoped>
.page-busy {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: var(--ctl-h);
  padding: var(--gap-1) var(--gap-2);
  color: var(--text-tertiary);
  font-size: var(--fs-aux);
}

.page-busy__card {
  display: inline-flex;
  align-items: center;
  gap: var(--gap-2);
}

.page-busy--overlay {
  position: absolute;
  inset: 0;
  z-index: 5;
  background: color-mix(in oklab, var(--surface-canvas) 55%, transparent);
  backdrop-filter: blur(2px);
  -webkit-backdrop-filter: blur(2px);
  animation: page-busy-in 160ms var(--ease) 120ms both;
}

.page-busy--overlay .page-busy__card {
  padding: 10px 14px 10px 12px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-pill);
  background: var(--surface-raised);
  color: var(--text-secondary);
  box-shadow: var(--shadow-md);
}

.page-busy-spin {
  width: 16px;
  height: 16px;
  color: var(--seal);
  animation: page-busy-spin 0.8s linear infinite;
}

.page-busy-label {
  font-weight: 500;
  letter-spacing: 0.01em;
}

@keyframes page-busy-spin {
  to {
    transform: rotate(1turn);
  }
}

@keyframes page-busy-in {
  from {
    opacity: 0;
  }
  to {
    opacity: 1;
  }
}

@media (prefers-reduced-motion: reduce) {
  .page-busy-spin,
  .page-busy--overlay {
    animation: none;
  }
}
</style>
