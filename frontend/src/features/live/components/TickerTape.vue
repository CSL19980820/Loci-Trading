<script setup lang="ts">
/*
 * 底部跑马灯，定高 22px。
 *
 * 两个改动：
 * 1. **无数据直接不渲染**。旧版空的时候把同一句会话级长文案平铺两遍
 *      （轨道要两份副本才能无缝循环），顶部于是出现两行冗余；
 *   2. 从顶部挪到底部（状态栏之上）。顶部已有顶栏 + 指数带两条定高信息带，
 *再叠一条滚动条会让视线起点全是动的东西。
 */
import { computed } from 'vue'
import StockLink from '@/shared/components/ui/StockLink.vue'
import { price, signedPct } from '@/shared/lib/format'
import type { QuoteRow } from '@/shared/api/marketStream'
import { formatTapeItem, type TapeItem } from '@/shared/lib/tape'

const props = withDefaults(defineProps<{ rows?: QuoteRow[] }>(), { rows: () => [] })

/** 轨道最多 60 条：再多也滚不完一圈，白付渲染成本 */
const items = computed<TapeItem[]>(() => (props.rows ?? []).slice(0, 60).map(formatTapeItem))

function toneClass(pct: number): string {
  if (pct > 0) return 'live-tone-up'
  if (pct < 0) return 'live-tone-down'
  return 'live-tone-flat'
}
</script>

<template>
  <div v-if="items.length" class="tape flex w-full flex-none items-center overflow-hidden">
    <div class="tape__track">
      <!-- 两份相同列表首尾相接 = 无缝循环；副本对读屏隐藏 -->
      <div v-for="copy in 2" :key="copy" class="tape__group" :aria-hidden="copy === 2 || undefined" :inert="copy === 2">
        <span v-for="item in items" :key="`${copy}-${item.key}`" class="tape__item">
          <StockLink :code="item.code" :name="item.name" :show-code="false" class="tape__name" />
          <span class="tape__px live-num" :class="toneClass(item.pct)">{{
            price(item.price)
          }}</span>
          <span class="tape__pct live-num" :class="toneClass(item.pct)">{{
            signedPct(item.pct)
          }}</span>
        </span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.tape {
  height: var(--live-tape-h);
  background-color: var(--live-panel);
  border-top: 1px solid var(--live-rule);
}

.tape__track {
  display: flex;
  width: max-content;
  will-change: transform;
  animation: tape-scroll 240s linear infinite;
}

.tape:hover .tape__track,
.tape:focus-within .tape__track {
  animation-play-state: paused;
}

.tape__group {
  display: flex;
  align-items: center;
  flex: none;
}

.tape__item {
  display: inline-flex;
  align-items: baseline;
  gap: var(--gap-1);
  padding: 0 var(--gap-3);
  border-right: 1px solid var(--live-rule-soft);
  font-size: var(--fs-kicker);
  white-space: nowrap;
}

:deep(.tape__name) {
  color: var(--live-muted);
  text-decoration: none;
}

:deep(.tape__name:hover) {
  color: var(--live-accent);
}

.tape__px {
  font-size: var(--fs-aux);
  font-weight: 600;
}

.tape__pct {
  font-size: var(--fs-kicker);
}

@keyframes tape-scroll {
  0% {
    transform: translate3d(0, 0, 0);
  }
  100% {
    transform: translate3d(-50%, 0, 0);
  }
}

@media (prefers-reduced-motion: reduce) {
  .tape { overflow-x: auto; }
  .tape__track {
    animation: none;
  }
}
</style>
