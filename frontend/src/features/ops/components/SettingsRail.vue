<script setup lang="ts">
export type RailMark = 'ok' | 'idle' | 'bad'

/** 二级项：同一页里的锚点段，不换 tab，只滚过去。 */
export type SettingsRailAnchor = {
  label: string
  /** 目标元素 id（不带 #），与 SettingsSection 的 anchor 一致 */
  anchor: string
}

export type SettingsRailItem = {
  name: string
  label: string
  tail?: string
  state?: RailMark
  /**
   * 页内锚点。
   *
   * 「系统」页里塞了数据目录 / 行情同步 / 推送 / 外观四段，rail 上却只有一个
   *「系统」——想配企微只能进去从头滚，滚到哪算哪。把四段摆出来才叫导航。
   */
  children?: SettingsRailAnchor[]
}

export type SettingsRailGroup = {
  title: string
  items: SettingsRailItem[]
}

defineProps<{
  modelValue: string
  groups: SettingsRailGroup[]
  /** 当前落在哪个锚点段（父层从路由 hash 传进来） */
  activeAnchor?: string
}>()

const emit = defineEmits<{
  'update:modelValue': [string]
  'select-anchor': [anchor: string]
}>()

function pick(name: string): void {
  emit('update:modelValue', name)
}

function onKeydown(event: KeyboardEvent, flat: string[]): void {
  const idx = flat.indexOf(
    (event.currentTarget as HTMLElement | null)?.dataset.name ?? '',
  )
  if (idx < 0) return
  let next = idx
  if (event.key === 'ArrowDown' || event.key === 'ArrowRight') next = Math.min(flat.length - 1, idx + 1)
  else if (event.key === 'ArrowUp' || event.key === 'ArrowLeft') next = Math.max(0, idx - 1)
  else if (event.key === 'Home') next = 0
  else if (event.key === 'End') next = flat.length - 1
  else return
  event.preventDefault()
  pick(flat[next]!)
  const el = document.querySelector<HTMLElement>(`[data-settings-rail="${flat[next]}"]`)
  el?.focus()
}
</script>

<template>
  <nav class="settings-rail" aria-label="设置分区">
    <div
      v-for="group in groups"
      :key="group.title"
      class="settings-rail__group"
      role="presentation"
    >
      <h3 class="settings-rail__group-title">{{ group.title }}</h3>
      <div
        role="tablist"
        aria-orientation="vertical"
        :aria-label="group.title"
        class="settings-rail__list"
      >
        <template v-for="item in group.items" :key="item.name">
          <el-button
            native-type="button"
            role="tab"
            class="settings-rail__item"
            :class="{ 'is-active': modelValue === item.name }"
            :aria-selected="modelValue === item.name"
            :tabindex="modelValue === item.name ? 0 : -1"
            :title="[item.label, item.tail].filter(Boolean).join(' · ')"
            :data-name="item.name"
            :data-settings-rail="item.name"
            @click="pick(item.name)"
            @keydown="
              onKeydown(
                $event,
                groups.flatMap((g) => g.items.map((i) => i.name)),
              )
            "
          >
            <span class="settings-rail__row">
              <span
                class="settings-rail__mark"
                :class="`settings-rail__mark--${item.state || 'idle'}`"
                aria-hidden="true"
              />
              <span class="settings-rail__label">{{ item.label }}</span>
              <span
                v-if="item.tail"
                class="settings-rail__tail"
                :class="{ 'is-bad': item.state === 'bad' }"
              >{{ item.tail }}</span>
            </span>
          </el-button>
          <!--
            二级锚点常驻：只在选中时才展开的话，从 MCP 页想去「推送」仍然是
            「先点系统 → 再找那一段」两步。四行短标签换一次点击，值。
          -->
          <div
            v-if="item.children?.length"
            class="settings-rail__anchors"
            role="group"
            :aria-label="`${item.label} · 分段`"
          >
            <el-button
              v-for="child in item.children"
              :key="child.anchor"
              link
              size="small"
              native-type="button"
              class="settings-rail__anchor"
              :class="{ 'is-active': modelValue === item.name && activeAnchor === child.anchor }"
              :aria-current="modelValue === item.name && activeAnchor === child.anchor"
              :data-settings-anchor="child.anchor"
              @click="emit('select-anchor', child.anchor)"
            >
              {{ child.label }}
            </el-button>
          </div>
        </template>
      </div>
    </div>
  </nav>
</template>

<style scoped>
.settings-rail {
  display: flex;
  flex-direction: column;
  gap: var(--gap-1);
  min-height: 0;
  overflow: auto;
  overscroll-behavior: contain;
  min-width: 0;
  padding: var(--gap-2);
  border: 1px solid var(--rule);
  border-radius: var(--radius);
  background: var(--surface);
}

.settings-rail__group {
  margin-bottom: var(--gap-1);
}

.settings-rail__group-title {
  margin: 0;
  padding: var(--gap-2) var(--gap-1);
  font-size: var(--fs-kicker);
  font-weight: 700;
  letter-spacing: 0.05em;
  color: var(--mist);
}

.settings-rail__list {
  display: flex;
  flex-direction: column;
  gap: var(--gap-1);
}

.settings-rail__item {
  width: 100%;
  margin: 0;
  padding: var(--gap-2);
  border: 1px solid transparent;
  border-radius: var(--radius);
  background: transparent;
  color: var(--ink);
  font-size: var(--fs-body);
  font-weight: 400;
  line-height: 1.25;
  text-align: left;
  cursor: pointer;
}

.settings-rail__item.el-button {
  height: auto;
  margin: 0;
  min-height: var(--ctl-h);
  border-radius: var(--radius);
  justify-content: flex-start;
  --el-button-text-color: var(--ink);
  --el-button-hover-text-color: var(--ink);
}

.settings-rail__item:hover {
  background: var(--surface-hover);
}

.settings-rail__item.is-active {
  border-color: var(--seal-border);
  background: var(--surface-active);
  color: var(--seal-ink);
  font-weight: 700;
}

/* EP 会再包一层，gap 要落在内部 row 上，否则字和摘要黏成一团 */
.settings-rail__row {
  display: flex;
  align-items: center;
  gap: var(--gap-2);
  width: 100%;
  min-width: 0;
}

/* 二级锚点：纯缩进 + 间距表达「这些属于上面那一项」；原 1px 左竖线是装饰，已删 */
.settings-rail__anchors {
  display: flex;
  flex-direction: column;
  margin: 0 0 var(--gap-1) var(--gap-4);
  padding-left: var(--gap-2);
}

.settings-rail__anchor.el-button {
  width: 100%;
  height: auto;
  margin: 0;
  min-height: var(--row-h-sm);
  padding: var(--gap-1) var(--gap-2);
  border-radius: var(--radius);
  justify-content: flex-start;
  font-size: var(--fs-aux);
  font-weight: 400;
  line-height: 1.2;
  text-align: left;
  --el-button-text-color: var(--muted);
  --el-button-hover-text-color: var(--ink);
  --el-button-active-text-color: var(--ink);
}

.settings-rail__anchor.el-button:hover {
  background: var(--surface-hover);
}

.settings-rail__anchor.el-button.is-active {
  color: var(--seal-ink);
  font-weight: 700;
}

.settings-rail__mark {
  width: 0.45rem;
  height: 0.45rem;
  flex-shrink: 0;
  border-radius: 50%;
  border: 1px solid color-mix(in oklab, var(--seal) 45%, var(--rule));
  background: transparent;
}

/* 状态由实际摘要驱动，不用动效吸引注意。 */
.settings-rail__mark--ok {
  border: none;
  background: var(--ok);
}

.settings-rail__mark--bad {
  border: none;
  background: var(--warn);
}

.settings-rail__mark--idle {
  background: transparent;
}

.settings-rail__label {
  flex: 1 1 auto;
  min-width: 0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.settings-rail__tail {
  flex-shrink: 0;
  margin-left: 0.25rem;
  font-family: var(--mono);
  font-size: var(--fs-kicker);
  color: var(--mist);
  white-space: nowrap;
}

.settings-rail__tail.is-bad {
  color: var(--warn);
}

.settings-rail__item:focus-visible,
.settings-rail__anchor:focus-visible {
  outline: 2px solid var(--seal);
  outline-offset: -2px;
}
</style>
