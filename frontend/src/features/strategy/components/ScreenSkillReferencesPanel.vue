<script setup lang="ts">
import { default as HintTooltip } from '@/shared/components/ui/app/HintTooltip.vue'
import { default as ActionButton } from '@/shared/components/ui/app/ActionButton.vue'
import { Notice, SurfaceCard } from '@/shared/components/ui/app/presentation'
import { default as FormField } from '@/shared/components/ui/app/FormField.vue'
import { default as TextField } from '@/shared/components/ui/app/TextField.vue'
import { default as ChoiceField } from '@/shared/components/ui/app/ChoiceField.vue'
import { default as ChoiceOption } from '@/shared/components/ui/app/ChoiceOption.vue'

import Sheet from '@/shared/components/layout/Sheet.vue'

import {
  isUsedReferenceRow,
  type ScreenSkillDraftModel,
} from '../composables/screenSkillDraft'
import { rowFieldError } from '../composables/screenSkillDraftIssues'

const props = withDefaults(
  defineProps<{
    draft: ScreenSkillDraftModel
    fieldErrors?: Record<string, string>
  }>(),
  { fieldErrors: () => ({}) },
)

const emit = defineEmits<{
  addReference: []
  removeReference: [index: number]
}>()

function refErr(index: number, id: string, part: string): string {
  return rowFieldError(props.fieldErrors, 'references', index, id, part)
}

function rowRequired(row: ScreenSkillDraftModel['references'][number]): boolean {
  return isUsedReferenceRow(row)
}
</script>

<template>
  <!--
    不留块标题：策略 / 数据 / 参数 / 资料这四块是 PageTabs 的互斥分区，
    高亮的那枚 tab 已经把「你在哪一块」交代完了，Sheet 再印一遍标题只是白占
    一行（用户原话：毫无意义的标题还丑）。Sheet 只留边框与内边距。
  -->
  <Sheet padded margin>
    <div class="section-head">
      <!-- 标题旁那句常驻介绍收进 tooltip：页面上不留介绍段（AGENTS.md 4） -->
      <HintTooltip placement="bottom-start" content="资料选填；填了就要补齐编号、标题与来源（链接 / 路径 / 章节 / 引文之一），逻辑里的引用编号要能对上这里。AI 生成草稿时必填">
        <strong class="section-head__title">引用台账</strong>
      </HintTooltip>
      <ActionButton size="small" @click="emit('addReference')">新增资料</ActionButton>
    </div>
    <Notice
      v-if="fieldErrors.references"
      :title="fieldErrors.references"
      tone="error"
      show-icon
      :closable="false"
      class="mb"
    />

    <div class="reference-list">
      <SurfaceCard
        v-for="(row, index) in props.draft.references"
        :key="row.id"
        shadow="never"
        class="reference-card"
        :class="{
          'reference-card--error': Boolean(
            refErr(index, row.id, 'id')
              || refErr(index, row.id, 'title')
              || refErr(index, row.id, 'kind')
              || refErr(index, row.id, 'locator'),
          ),
        }"
      >
        <template #header>
          <div class="reference-card__head">
            <span>{{ row.id || `资料 ${index + 1}` }}</span>
            <ActionButton variant="ghost" tone="danger" size="small" @click="emit('removeReference', index)">删除</ActionButton>
          </div>
        </template>

        <div class="meta-grid">
          <FormField label="资料编号" :required="rowRequired(row)" :error="refErr(index, row.id, 'id')">
            <TextField v-model.trim="row.id" maxlength="48" placeholder="例如 ref-ma-handbook" />
          </FormField>
          <FormField label="标题" :required="rowRequired(row)" :error="refErr(index, row.id, 'title')">
            <TextField v-model.trim="row.title" maxlength="80" placeholder="均线手册 / 研报 / 笔记标题" />
          </FormField>
          <FormField label="类型" :required="rowRequired(row)" :error="refErr(index, row.id, 'kind')">
            <ChoiceField v-model="row.kind" allow-create filterable default-first-option class="full">
              <ChoiceOption label="研报" value="report" />
              <ChoiceOption label="文档" value="doc" />
              <ChoiceOption label="论文" value="paper" />
              <ChoiceOption label="笔记" value="note" />
              <ChoiceOption label="代码" value="code" />
            </ChoiceField>
          </FormField>
          <FormField label="链接" :error="refErr(index, row.id, 'locator')">
            <TextField v-model.trim="row.url" placeholder="网页地址，选填" />
          </FormField>
          <FormField label="本地路径">
            <TextField v-model.trim="row.path" placeholder="本机或仓库内文件路径，选填" />
          </FormField>
          <FormField label="章节 / 页码">
            <TextField v-model.trim="row.section" placeholder="例如 第 2 节 / 第 8-10 页" />
          </FormField>
        </div>

        <FormField label="关键引文">
          <TextField
            v-model.trim="row.quote"
            type="textarea"
            :rows="3"
            placeholder="摘录关键信息，便于复核 AI 与逻辑是否对齐。"
          />
        </FormField>
      </SurfaceCard>
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
.reference-card__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
}

.reference-list {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.reference-card {
  border-color: color-mix(in oklab, var(--rule) 84%, transparent);
}

.reference-card--error {
  border-color: var(--stamp);
}

.mb {
  margin-bottom: 0.75rem;
}

/* 小节标题压成一行：标题与它的操作按钮同高同行，不再是标题一行、介绍一行 */
.section-head__title {
  font-size: var(--fs-title);
  font-weight: 700;
  letter-spacing: 0.03em;
  cursor: help;
}

.section-head {
  margin-bottom: var(--gap-2);
}

@media (max-width: 640px) {
  .meta-grid {
    grid-template-columns: 1fr;
  }
}
</style>
