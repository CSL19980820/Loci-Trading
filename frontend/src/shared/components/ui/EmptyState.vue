<script setup lang="ts">
import { computed } from 'vue'

/**
 * 空态 —— 一行主文案 + 最多一个主操作，整块不超过 96px。
 *
 * 旧版是「大插图 + 三行解释 + 96px 图」，在密表页里一块空态比它要解释的表还高。
 * 规范（docs/ui-spec.md 空态规范）：主文案 ≤14 字讲「为什么空」，`reason` 一行讲
 * 「下一步」，两者合计 ≤24 字；插图一律不要——空不是异常，不需要一张图来渲染情绪。
 */
const props = withDefaults(
  defineProps<{
    /** 为什么空，≤14 字 */
    description?: string
    /** 下一步做什么；与 description 合计 ≤24 字，单行显示 */
    reason?: string
    /** 可选：预计恢复/产出时间，接在 reason 后同一行 */
    eta?: string
    /** @deprecated 空态不再有插图，保留仅为不破坏存量调用 */
    imageSize?: number
  }>(),
  {
    // 默认值不该是一句可以直接交付的墓碑：调用方应当讲清「这里会出现什么」
    description: '这里还没有记录',
  },
)

const hint = computed(() => {
  const parts = [props.reason, props.eta ? `预计 ${props.eta}` : ''].filter(Boolean)
  return parts.join('；')
})
</script>

<template>
  <div class="empty-state">
    <p class="empty-state__main">{{ description }}</p>
    <p v-if="hint" class="empty-state__hint" :title="hint">{{ hint }}</p>
    <div v-if="$slots.default" class="empty-state__act">
      <slot />
    </div>
  </div>
</template>

<style scoped>
/*
 * 不用 el-empty：它自带插图槽与 40px 上下留白，收到 96px 以内要逐条对抗它的默认值，
 * 收完也只剩三个纯文本节点——那就直接三个节点。交互仍由调用方传 el-button。
 */
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--gap-1);
  max-height: 96px;
  padding: var(--gap-3) var(--gap-2);
  overflow: hidden;
  text-align: center;
}

.empty-state__main {
  margin: 0;
  font-size: var(--fs-body);
  font-weight: 600;
  line-height: 1.4;
  color: var(--muted);
}

.empty-state__hint {
  margin: 0;
  max-width: 48ch;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: var(--fs-aux);
  line-height: 1.4;
  color: var(--mist);
}

.empty-state__act {
  display: flex;
  align-items: center;
  gap: var(--gap-2);
  margin-top: 1px;
}
</style>
