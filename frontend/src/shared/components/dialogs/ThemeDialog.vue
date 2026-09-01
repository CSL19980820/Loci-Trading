<script setup lang="ts">
import { computed } from 'vue'

import { useThemeStore } from '@/shared/stores/theme'
import { contrastRatio } from '@/shared/lib/theme'

defineProps<{ modelValue: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [boolean] }>()
const store = useThemeStore()

/**
 * 取色器给的色和实际落地的色差多远。差得明显就提示「已按对比度自动校正」——
 * 用户选了淡黄却看到深黄不是 bug，是系统把亮度压到白字能读的位置（见 lib/theme.ts）。
 */
const corrected = computed((): boolean => {
  const picked = store.customColor
  const solid = store.customScale['--seal']
  return contrastRatio(picked, solid) > 1.35
})

function close(): void {
  emit('update:modelValue', false)
}
</script>

<template>
  <el-dialog
    :model-value="modelValue"
    title="主题"
    width="min(92vw, 460px)"
    class="theme-dialog"
    destroy-on-close
    @update:model-value="emit('update:modelValue', $event)"
  >
    <section class="theme-block">
      <h3 class="theme-block__kicker">外观</h3>
      <div class="appearance-row">
        <button
          v-for="item in store.appearances"
          :key="item.id"
          type="button"
          class="appearance"
          :class="{ 'appearance--on': store.appearanceId === item.id }"
          :aria-pressed="store.appearanceId === item.id"
          @click="store.setAppearance(item.id)"
        >
          <!-- 真实配色预览：画布上摆一块面板 + 一条分隔线 + 两行字，四档并排能一眼分出来 -->
          <span
            class="appearance__scene"
            :style="{ background: item.preview.canvas, borderColor: item.preview.border }"
            aria-hidden="true"
          >
            <span
              class="appearance__panel"
              :style="{ background: item.preview.surface, borderColor: item.preview.border }"
            >
              <span class="appearance__line" :style="{ background: item.preview.text }" />
              <span
                class="appearance__line appearance__line--short"
                :style="{ background: item.preview.border }"
              />
            </span>
          </span>
          <span class="appearance__label">{{ item.label }}</span>
          <span class="appearance__hint">{{ item.hint }}</span>
        </button>
      </div>
    </section>

    <section class="theme-block">
      <h3 class="theme-block__kicker">主色</h3>
      <div class="swatch-row">
        <button
          v-for="item in store.primaries"
          :key="item.id"
          type="button"
          class="swatch"
          :class="{ 'swatch--on': store.primaryId === item.id }"
          :style="{ '--sw': item.color }"
          :aria-pressed="store.primaryId === item.id"
          :title="item.label"
          @click="store.setPrimary(item.id)"
        >
          <span class="swatch__chip" aria-hidden="true" />
          {{ item.label }}
        </button>
      </div>
    </section>

    <section class="theme-block">
      <h3 class="theme-block__kicker">自定义</h3>
      <div class="custom-row">
        <el-color-picker
          :model-value="store.customColor"
          :predefine="store.presets"
          size="small"
          @change="store.setCustomPrimary($event ?? store.customColor)"
        />
        <span class="custom-hint" :class="{ 'custom-hint--on': store.isCustom && corrected }">
          {{ store.isCustom && corrected ? '已按对比度自动校正' : '任选一色，即时生效' }}
        </span>
      </div>
      <!-- 实时预览用真控件：主按钮/次按钮/链接/选中标签，一眼看出对比度是否可用 -->
      <div class="preview-row">
        <el-button type="primary" size="small">主按钮</el-button>
        <el-button size="small">次按钮</el-button>
        <a class="preview-link" href="#" @click.prevent>链接文字</a>
        <el-tag size="small" effect="light">选中标签</el-tag>
      </div>
    </section>

    <template #footer>
      <el-button type="primary" @click="close">用这套</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
/* 选一下就即时生效，所以没有「取消」：footer 只留一个收工按钮 */
.theme-block + .theme-block {
  margin-top: var(--gap-3);
}

.theme-block__kicker {
  margin: 0 0 var(--gap-2);
  color: var(--text-tertiary);
  font-size: var(--fs-kicker);
  font-weight: 600;
  letter-spacing: 0.06em;
}

.appearance-row {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: var(--gap-2);
}

.appearance {
  display: flex;
  flex-direction: column;
  align-items: stretch;
  gap: 3px;
  padding: 0;
  border: 0;
  background: none;
  text-align: left;
}

.appearance__scene {
  display: flex;
  align-items: flex-end;
  height: 44px;
  padding: 6px 6px 0;
  border: 1px solid;
  border-radius: var(--radius);
}

.appearance--on .appearance__scene {
  outline: 2px solid var(--seal);
  outline-offset: 1px;
}

.appearance__panel {
  flex: 1;
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: 3px;
  height: 100%;
  padding: 0 5px;
  border: 1px solid;
  border-bottom: 0;
  border-radius: var(--radius) var(--radius) 0 0;
}

.appearance__line {
  height: 3px;
  width: 100%;
  border-radius: 2px;
  opacity: 0.85;
}

.appearance__line--short {
  width: 62%;
}

.appearance__label {
  color: var(--text-primary);
  font-size: var(--fs-aux);
  font-weight: 600;
}

.appearance--on .appearance__label {
  color: var(--seal-ink);
}

.appearance__hint {
  color: var(--text-tertiary);
  font-size: var(--fs-kicker);
}

.swatch-row {
  display: flex;
  flex-wrap: wrap;
  gap: var(--gap-1);
}

.swatch {
  display: inline-flex;
  align-items: center;
  height: var(--ctl-h);
  padding: 0 var(--gap-2);
  border: 1px solid var(--border-default);
  border-radius: var(--radius);
  background: var(--surface);
  color: var(--text-primary);
  font-size: var(--fs-body);
  font-weight: 500;
}

.swatch:hover {
  border-color: var(--seal-border);
}

/* 选中态用品牌描边 + 极淡品牌底，不用阴影（D3） */
.swatch--on {
  border-color: var(--seal);
  background: var(--seal-soft);
  color: var(--seal-ink);
}

.swatch__chip {
  width: 10px;
  height: 10px;
  margin-right: var(--gap-1);
  border: 1px solid color-mix(in oklab, var(--n-12) 12%, transparent);
  border-radius: 999px;
  background: var(--sw);
}

.custom-row {
  display: flex;
  align-items: center;
  gap: var(--gap-2);
}

.custom-hint {
  color: var(--text-tertiary);
  font-size: var(--fs-aux);
}

.custom-hint--on {
  color: var(--warn);
}

.preview-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--gap-2);
  margin-top: var(--gap-2);
  padding: var(--gap-2);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius);
  background: var(--surface-sunken);
}

.preview-link {
  color: var(--seal-ink);
  font-size: var(--fs-body);
  font-weight: 600;
  text-decoration: none;
}
</style>
