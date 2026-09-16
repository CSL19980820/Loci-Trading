<script setup lang="ts">
import type { SectionStamp } from '../composables/useSystemSettings'

defineProps<{
  title: string
  stamp: SectionStamp
  anchor: string
  error?: string
}>()
</script>

<template>
  <!--
    标题保留：同屏并列四小节（数据目录 / 行情同步 / 推送 / 外观），遮住标题就分不清
    哪块表单是哪联。压成一行的做法是左槽定宽——标题与该小节第一条控件永远同高，
    窄屏也只收窄槽宽，绝不让标题独占一行（见下方 media query）。
  -->
  <section :id="anchor" class="sys-section" :aria-label="title">
    <aside class="sys-section__gutter">
      <h3 class="sys-section__title">{{ title }}</h3>
      <p
        class="sys-section__stamp"
        role="status"
        :class="`sys-section__stamp--${stamp.kind}`"
      >
        <span
          v-if="stamp.kind === 'dirty' || stamp.kind === 'pending'"
          class="sys-section__mark"
          aria-hidden="true"
        />
        <template v-if="stamp.kind === 'dirty'">未存</template>
        <template v-else-if="stamp.kind === 'saved'">已存 {{ stamp.at }}</template>
        <template v-else-if="stamp.kind === 'instant'">即时</template>
        <template v-else-if="stamp.kind === 'pending'">待生效</template>
      </p>
    </aside>
    <div class="sys-section__body">
      <slot />
      <el-alert
        v-if="error"
        :title="error"
        type="error"
        show-icon
        :closable="false"
        class="sys-section__err"
      />
      <div v-if="$slots.actions" class="sys-section__actions">
        <slot name="actions" />
      </div>
    </div>
  </section>
</template>

<style scoped>
.sys-section {
  display: grid;
  grid-template-columns: 5.75rem minmax(0, 1fr);
  gap: 0.35rem 1.1rem;
  padding: 0.7rem 0;
  border-top: 1px solid var(--rule);
  width: 100%;
  scroll-margin-top: 0.35rem;
}

.sys-section:first-of-type {
  border-top: 0;
  padding-top: 0.15rem;
}

.sys-section__gutter {
  min-width: 0;
  padding-top: 0.2rem;
  border-right: 1px solid color-mix(in oklab, var(--rule) 70%, transparent);
  padding-right: 0.75rem;
}

.sys-section__title {
  margin: 0;
  font-size: 0.84rem;
  font-weight: 650;
  color: var(--ink);
  line-height: 1.25;
  letter-spacing: 0.01em;
}

.sys-section__stamp {
  display: flex;
  align-items: center;
  gap: 0.3rem;
  margin: 0.25rem 0 0;
  min-height: 0.9rem;
  font-family: var(--mono);
  font-size: 0.64rem;
  letter-spacing: 0.05em;
  color: var(--mist);
}

.sys-section__stamp--dirty {
  color: var(--seal-ink);
}

.sys-section__stamp--pending {
  color: var(--muted);
}

.sys-section__mark {
  width: 0.35rem;
  height: 0.35rem;
  flex-shrink: 0;
  background: var(--seal);
}

.sys-section__stamp--pending .sys-section__mark {
  background: var(--mist);
}

.sys-section__body {
  min-width: 0;
  width: 100%;
}

.sys-section__err {
  margin-top: 0.4rem;
}

.sys-section__actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem;
  margin-top: 0.25rem;
}

/*
 * 窄屏只收窄左槽，**不塌成单列**：塌了标题就自己占一行、表单退到下一行，
 * 正是要避免的「两行干一行的事」。
 */
@media (max-width: 900px) {
  .sys-section {
    grid-template-columns: 4.5rem minmax(0, 1fr);
    gap: 0.25rem 0.55rem;
  }

  .sys-section__gutter {
    padding-right: 0.4rem;
  }

  .sys-section__title {
    font-size: var(--fs-aux);
  }
}
</style>
