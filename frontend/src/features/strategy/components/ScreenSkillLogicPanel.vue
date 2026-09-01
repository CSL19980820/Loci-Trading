<script setup lang="ts">
import Sheet from '@/shared/components/layout/Sheet.vue'

import type { ScreenSkillDraftModel } from '../composables/screenSkillDraft'
import { rowFieldError } from '../composables/screenSkillDraftIssues'

const props = withDefaults(
  defineProps<{
    draft: ScreenSkillDraftModel
    fieldErrors?: Record<string, string>
  }>(),
  { fieldErrors: () => ({}) },
)

const emit = defineEmits<{
  addLogic: []
  removeLogic: [index: number]
}>()

function err(field: string): string {
  return props.fieldErrors[field] || ''
}

function logicErr(index: number, id: string, part: string): string {
  return rowFieldError(props.fieldErrors, 'logic', index, id, part)
}
</script>

<template>
  <!--
    不留块标题：策略 / 数据 / 参数 / 资料这四块是 PageTabs 的互斥分区，
    高亮的那枚 tab 已经把「你在哪一块」交代完了，Sheet 再印一遍标题只是白占
    一行（用户原话：毫无意义的标题还丑）。Sheet 只留边框与内边距。
  -->
  <Sheet padded margin>
    <div class="meta-grid">
      <el-form-item label="标识" required :error="err('slug')">
        <el-input
          v-model.trim="props.draft.slug"
          maxlength="64"
          placeholder="小写英文与连字符，例如 breakout-ma"
        />
      </el-form-item>
      <el-form-item label="名称" required :error="err('name')">
        <el-input v-model.trim="props.draft.name" maxlength="64" placeholder="我的突破战法" />
      </el-form-item>
      <el-form-item label="版本">
        <el-input v-model.trim="props.draft.version" maxlength="32" placeholder="0.1.0" />
      </el-form-item>
      <el-form-item label="启用">
        <el-switch v-model="props.draft.enabled" inline-prompt active-text="开" inactive-text="关" />
      </el-form-item>
      <el-form-item label="入场时点">
        <el-select v-model="props.draft.entryTiming" class="full">
          <el-option label="当日开盘" value="open" />
          <el-option label="当日收盘" value="close" />
          <el-option label="次日开盘" value="next_open" />
          <el-option label="次日低吸" value="next_dip" />
        </el-select>
      </el-form-item>
      <el-form-item label="最少 K 线" :error="err('minBars')">
        <el-input-number v-model="props.draft.minBars" :min="1" :max="1000" :controls="false" class="full" />
      </el-form-item>
      <el-form-item label="主信号名" required :error="err('signal')">
        <el-input v-model.trim="props.draft.signal" maxlength="32" placeholder="例如 入选" />
      </el-form-item>
      <el-form-item label="运行时">
        <el-input :model-value="props.draft.runtime === 'python' ? '脚本' : '公式'" readonly />
      </el-form-item>
    </div>

    <el-form-item label="说明" required :error="err('description')">
      <el-input
        v-model.trim="props.draft.description"
        type="textarea"
        :rows="3"
        maxlength="240"
        placeholder="说明入选逻辑、适用阶段、风险与禁用场景。"
      />
    </el-form-item>

    <el-form-item label="因子清单" required :error="err('factorsText')">
      <el-input
        v-model="props.draft.factorsText"
        type="textarea"
        :rows="2"
        placeholder="用逗号或换行分隔，例如 均线、量比、突破"
      />
    </el-form-item>

    <div class="section-head">
      <!-- 标题旁那句常驻介绍收进 tooltip：页面上不留介绍段（AGENTS.md 4） -->
      <el-tooltip placement="bottom-start" content="每条逻辑单独记录表达式、解释与引用编号">
        <strong class="section-head__title">逻辑卡片</strong>
      </el-tooltip>
      <el-button size="small" @click="emit('addLogic')">新增逻辑</el-button>
    </div>

    <div class="logic-list">
      <el-card
        v-for="(row, index) in props.draft.logic"
        :key="row.id"
        shadow="never"
        class="logic-card"
        :class="{ 'logic-card--error': Boolean(logicErr(index, row.id, 'id') || logicErr(index, row.id, 'title') || logicErr(index, row.id, 'expression') || logicErr(index, row.id, 'explanation') || logicErr(index, row.id, 'citationsText')) }"
      >
        <template #header>
          <div class="logic-card__head">
            <span>{{ row.id || `逻辑 ${index + 1}` }}</span>
            <el-button text type="danger" size="small" @click="emit('removeLogic', index)">删除</el-button>
          </div>
        </template>
        <div class="meta-grid">
          <el-form-item label="逻辑编号" required :error="logicErr(index, row.id, 'id')">
            <el-input v-model.trim="row.id" maxlength="40" placeholder="例如 logic-breakout" />
          </el-form-item>
          <el-form-item label="标题" required :error="logicErr(index, row.id, 'title')">
            <el-input v-model.trim="row.title" maxlength="64" placeholder="站上均线" />
          </el-form-item>
        </div>
        <el-form-item label="表达式" required :error="logicErr(index, row.id, 'expression')">
          <el-input
            v-model.trim="row.expression"
            type="textarea"
            :rows="2"
            placeholder="例如 CLOSE > MA(CLOSE, N)"
          />
        </el-form-item>
        <el-form-item label="解释" required :error="logicErr(index, row.id, 'explanation')">
          <el-input
            v-model.trim="row.explanation"
            type="textarea"
            :rows="3"
            placeholder="说明该逻辑为何存在、适用什么行情。"
          />
        </el-form-item>
        <el-form-item label="引用编号" :error="logicErr(index, row.id, 'citationsText')">
          <el-input
            v-model="row.citationsText"
            type="textarea"
            :rows="2"
            placeholder="逗号或换行分隔，填资料页里的编号"
          />
        </el-form-item>
      </el-card>
    </div>
  </Sheet>
</template>

<style scoped>
.meta-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0.55rem 0.75rem;
}

.full {
  width: 100%;
}

.section-head,
.logic-card__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
}

.logic-list {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.logic-card {
  border-color: color-mix(in srgb, var(--rule) 84%, transparent);
}

.logic-card--error {
  border-color: var(--el-color-danger);
}

/* 小节标题压成一行：标题与它的操作按钮同高同行，不再是标题一行、介绍一行 */
.section-head {
  margin-bottom: var(--gap-2);
}

.section-head__title {
  font-size: var(--fs-title);
  font-weight: 700;
  letter-spacing: 0.03em;
  cursor: help;
}

@media (max-width: 640px) {
  .meta-grid {
    grid-template-columns: 1fr;
  }
}
</style>
