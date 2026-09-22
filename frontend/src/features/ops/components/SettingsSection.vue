<script setup lang="ts">
import { Alert, AlertTitle } from '@/shared/components/ui/alert'
import { TriangleAlert } from '@lucide/vue'

import type { SectionStamp } from '../composables/useSystemSettings'

/**
 * 系统页里的一节（数据目录 / 行情同步 / 推送 / 外观）。
 *
 * 一节 = 一张卡：头部是小节标题 + 保存状态戳，正文是一组 **设置行**
 * （`.settings-row`：左侧标签 + 一句说明，右侧控件，行间 hairline），
 * 底部可选一行次要操作。`.settings-row` 的样式在这里用 `:deep` 定义一次，
 * 各 Sys* 分节只管排内容，不再各写一套 6.5em 标签槽。
 */
defineProps<{
  title: string
  description?: string
  stamp: SectionStamp
  anchor: string
  error?: string
}>()
</script>

<template>
  <section :id="anchor" class="sys-card" :aria-label="title">
    <header class="sys-card__head">
      <div class="sys-card__lead">
        <h3 class="sys-card__title">{{ title }}</h3>
      </div>
      <p
        class="sys-card__stamp"
        role="status" v-if="stamp.kind !== 'clean'"
        :class="`sys-card__stamp--${stamp.kind}`"
      >
        <span class="sys-card__stamp-dot" aria-hidden="true" />
        <template v-if="stamp.kind === 'dirty'">未保存</template>
        <template v-else-if="stamp.kind === 'saved'">已存 {{ stamp.at }}</template>
        <template v-else-if="stamp.kind === 'instant'">即时生效</template>
        <template v-else-if="stamp.kind === 'pending'">待生效</template>
      </p>
    </header>
    <div class="sys-card__body">
      <slot />
    </div>
    <Alert v-if="error" variant="destructive" class="sys-card__err">
      <TriangleAlert />
      <AlertTitle class="line-clamp-none">{{ error }}</AlertTitle>
    </Alert>
    <footer v-if="$slots.actions" class="sys-card__foot">
      <slot name="actions" />
    </footer>
  </section>
</template>

<style scoped>
.sys-card {
  display: flex;
  flex-direction: column;
  min-width: 0;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-lg);
  background: var(--surface);
  box-shadow: var(--shadow-xs);
  scroll-margin-top: var(--gap-3);
  overflow: hidden;
}

.sys-card__head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--gap-3);
  padding: 12px 16px;
  border-bottom: 1px solid var(--border-subtle);
}

.sys-card__lead {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.sys-card__title {
  margin: 0;
  color: var(--text-primary);
  font-size: var(--fs-title);
  font-weight: 600;
  letter-spacing: -0.01em;
  line-height: 1.3;
}

.sys-card__desc {
  margin: 0;
  color: var(--text-tertiary);
  font-size: var(--fs-aux);
  line-height: 1.5;
}

.sys-card__stamp {
  display: inline-flex;
  flex-shrink: 0;
  align-items: center;
  gap: 6px;
  margin: 0;
  padding: 2px 8px 2px 6px;
  border-radius: var(--radius-pill);
  background: var(--surface-sunken);
  color: var(--text-tertiary);
  font-family: var(--mono);
  font-size: var(--fs-kicker);
  font-weight: 500;
  line-height: 1.6;
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
}

.sys-card__stamp-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--border-strong);
}

.sys-card__stamp--dirty {
  background: var(--seal-soft);
  color: var(--seal-ink);
}

.sys-card__stamp--dirty .sys-card__stamp-dot {
  background: var(--seal);
}

.sys-card__stamp--saved .sys-card__stamp-dot {
  background: var(--ok);
}

.sys-card__stamp--pending {
  background: var(--warn-soft);
  color: var(--warn-ink);
}

.sys-card__stamp--pending .sys-card__stamp-dot {
  background: var(--warn);
}

.sys-card__body {
  min-width: 0;
}

.sys-card__err {
  margin: var(--gap-3) var(--gap-4) 0;
}

.sys-card__foot {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: var(--gap-2);
  padding: var(--gap-3) var(--gap-4);
  border-top: 1px solid var(--border-subtle);
  background: var(--surface-sunken);
}

/* ─── 设置行：各 Sys* 分节共用 ─── */
.sys-card__body :deep(.settings-row) {
  display: grid;
  grid-template-columns: minmax(0, 1.1fr) minmax(0, 1.6fr);
  align-items: center;
  gap: var(--gap-2) var(--gap-4);
  min-height: 48px;
  padding: var(--gap-3) var(--gap-4);
  border-top: 1px solid var(--border-subtle);
}

.sys-card__body :deep(.settings-row:first-child) {
  border-top: 0;
}

.sys-card__body :deep(.settings-row--stack) {
  grid-template-columns: minmax(0, 1fr);
}

.sys-card__body :deep(.settings-row__lead) {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.sys-card__body :deep(.settings-row__label) {
  color: var(--text-primary);
  font-size: var(--fs-ui);
  font-weight: 500;
  line-height: 1.35;
}

.sys-card__body :deep(.settings-row__desc) {
  margin: 0;
  color: var(--text-tertiary);
  font-size: var(--fs-aux);
  line-height: 1.5;
}

.sys-card__body :deep(.settings-row__control) {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: flex-end;
  gap: var(--gap-2) var(--gap-3);
  min-width: 0;
}

.sys-card__body :deep(.settings-row--stack .settings-row__control) {
  justify-content: flex-start;
}

.sys-card__body :deep(.settings-row__note) {
  grid-column: 1 / -1;
  margin: 0;
  color: var(--text-tertiary);
  font-size: var(--fs-aux);
}

@media (max-width: 640px) {
  .sys-card__head {
    padding: var(--gap-3);
  }

  .sys-card__foot {
    padding: var(--gap-3);
  }

  .sys-card__err {
    margin: var(--gap-3) var(--gap-3) 0;
  }

  .sys-card__body :deep(.settings-row) {
    grid-template-columns: minmax(90px, .8fr) minmax(0, 1.2fr);
    padding: var(--gap-3);
  }

  .sys-card__body :deep(.settings-row__control) {
    justify-content: flex-end;
  }
  .sys-card__body :deep(.settings-row--stack) { grid-template-columns: minmax(0, 1fr); }
  .sys-card__body :deep(.settings-row--stack .settings-row__control) { justify-content: flex-start; }
}
</style>
