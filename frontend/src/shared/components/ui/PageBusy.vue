<script setup lang="ts">
import { Loading } from '@element-plus/icons-vue'

/**
 * 加载态 —— 一行 28px 的转圈 + 文案，不占版面。
 *
 * 骨架/加载态不许撑出大块空白（D3）：此前 min-height 4.5rem + 1rem padding，
 * 一个「加载中…」能顶掉 100px 高度；现在整块就是一行控件高。
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
    <el-icon class="page-busy-spin is-loading" aria-hidden="true">
      <Loading />
    </el-icon>
    <span class="page-busy-label">{{ label }}</span>
  </div>
</template>

<style scoped>
.page-busy {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--gap-2);
  min-height: var(--ctl-h);
  padding: var(--gap-1) var(--gap-2);
  color: var(--mist);
  font-size: var(--fs-aux);
}

.page-busy--overlay {
  position: absolute;
  inset: 0;
  z-index: 5;
  background: color-mix(in srgb, var(--sheet) 78%, transparent);
}

.page-busy-spin {
  color: var(--seal-ink);
  font-size: var(--fs-title);
}

.page-busy-label {
  letter-spacing: 0.04em;
}

@media (prefers-reduced-motion: reduce) {
  .page-busy-spin.is-loading {
    animation: none;
  }
}
</style>
