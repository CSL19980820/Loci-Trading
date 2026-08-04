<script setup lang="ts">
export type ReceiptPair = {
  key: string
  value: string
  hint?: string
}

withDefaults(
  defineProps<{
    title: string
    /** 标题旁的静默状态（非导航） */
    receipt?: ReceiptPair[]
    /** @deprecated 表单不再限宽；保留 prop 以免旧调用报错 */
    form?: boolean
    /** 名册型：body 吃满剩余高度 */
    fill?: boolean
  }>(),
  {
    receipt: () => [],
    form: false,
    fill: false,
  },
)
</script>

<template>
  <section class="settings-panel" :class="{ 'settings-panel--fill': fill }">
    <header class="settings-panel__head">
      <h2 class="settings-panel__title">{{ title }}</h2>
      <p v-if="receipt.length" class="settings-panel__receipt" aria-label="状态回执">
        <template v-for="(pair, i) in receipt" :key="pair.key">
          <span v-if="i > 0" class="settings-panel__sep" aria-hidden="true">·</span>
          <span class="settings-panel__pair" :title="pair.hint">
            <span class="settings-panel__k">{{ pair.key }}</span>
            {{ pair.value }}
          </span>
        </template>
      </p>
      <div v-if="$slots.action" class="settings-panel__action">
        <slot name="action" />
      </div>
    </header>
    <div class="settings-panel__body">
      <slot />
    </div>
    <footer v-if="$slots.foot" class="settings-panel__foot">
      <slot name="foot" />
    </footer>
  </section>
</template>

<style scoped>
.settings-panel {
  display: flex;
  flex-direction: column;
  min-height: 0;
  flex: 1 1 auto;
  background: var(--sheet);
}

.settings-panel__head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.4rem 0.75rem;
  padding: 0.4rem 0.85rem;
  flex-shrink: 0;
  border-bottom: 1px solid var(--rule);
  min-height: 2.4rem;
}

.settings-panel__title {
  margin: 0;
  flex: 0 0 auto;
  font-family: var(--font-display);
  font-size: 0.98rem;
  font-weight: 600;
  color: var(--ink);
  letter-spacing: 0.01em;
  line-height: 1.2;
}

.settings-panel__receipt {
  margin: 0;
  min-width: 0;
  flex: 1 1 auto;
  font-family: var(--mono);
  font-size: 0.72rem;
  font-variant-numeric: tabular-nums;
  color: var(--muted);
  line-height: 1.3;
}

.settings-panel__sep {
  margin: 0 0.4rem;
  color: var(--rule);
}

.settings-panel__pair {
  white-space: nowrap;
}

.settings-panel__k {
  color: var(--mist);
  margin-right: 0.25rem;
}

.settings-panel__action {
  margin-left: auto;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.35rem;
  flex: 0 0 auto;
}

.settings-panel__body {
  flex: 1 1 auto;
  min-height: 0;
  overflow: auto;
  padding: 0.55rem 0.85rem 0.75rem;
  width: 100%;
}

.settings-panel--fill .settings-panel__body {
  display: flex;
  flex-direction: column;
  overflow: hidden;
  padding: 0;
}

.settings-panel__foot {
  display: flex;
  flex-wrap: wrap;
  gap: 0.45rem;
  justify-content: flex-end;
  align-items: center;
  padding: 0.45rem 0.85rem;
  border-top: 1px solid var(--rule);
  flex-shrink: 0;
  width: 100%;
}

@media (max-width: 720px) {
  .settings-panel__receipt {
    flex: 1 1 100%;
    order: 3;
  }

  .settings-panel__action {
    margin-left: 0;
  }
}
</style>
