<script setup lang="ts">
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
  <Sheet title="资料来源" padded margin>
    <div class="section-head">
      <div>
        <strong>引用台账</strong>
        <div class="dim">
          资料为可选项，不填也能试跑与保存。只有动手填写某条资料时，才需要补齐编号、标题，以及链接 / 路径 / 章节 / 引文之一；逻辑里写了引用编号时也要能对应到这里。AI 生成草稿时才强制要求资料。
        </div>
      </div>
      <el-button size="small" @click="emit('addReference')">新增资料</el-button>
    </div>
    <el-alert
      v-if="fieldErrors.references"
      :title="fieldErrors.references"
      type="error"
      show-icon
      :closable="false"
      class="mb"
    />

    <div class="reference-list">
      <el-card
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
            <el-button text type="danger" size="small" @click="emit('removeReference', index)">删除</el-button>
          </div>
        </template>

        <div class="meta-grid">
          <el-form-item label="资料编号" :required="rowRequired(row)" :error="refErr(index, row.id, 'id')">
            <el-input v-model.trim="row.id" maxlength="48" placeholder="例如 ref-ma-handbook" />
          </el-form-item>
          <el-form-item label="标题" :required="rowRequired(row)" :error="refErr(index, row.id, 'title')">
            <el-input v-model.trim="row.title" maxlength="80" placeholder="均线手册 / 研报 / 笔记标题" />
          </el-form-item>
          <el-form-item label="类型" :required="rowRequired(row)" :error="refErr(index, row.id, 'kind')">
            <el-select v-model="row.kind" allow-create filterable default-first-option class="full">
              <el-option label="研报" value="report" />
              <el-option label="文档" value="doc" />
              <el-option label="论文" value="paper" />
              <el-option label="笔记" value="note" />
              <el-option label="代码" value="code" />
            </el-select>
          </el-form-item>
          <el-form-item label="链接" :error="refErr(index, row.id, 'locator')">
            <el-input v-model.trim="row.url" placeholder="网页地址，选填" />
          </el-form-item>
          <el-form-item label="本地路径">
            <el-input v-model.trim="row.path" placeholder="本机或仓库内文件路径，选填" />
          </el-form-item>
          <el-form-item label="章节 / 页码">
            <el-input v-model.trim="row.section" placeholder="例如 第 2 节 / 第 8-10 页" />
          </el-form-item>
        </div>

        <el-form-item label="关键引文">
          <el-input
            v-model.trim="row.quote"
            type="textarea"
            :rows="3"
            placeholder="摘录关键信息，便于复核 AI 与逻辑是否对齐。"
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
  border-color: color-mix(in srgb, var(--rule) 84%, transparent);
}

.reference-card--error {
  border-color: var(--el-color-danger);
}

.mb {
  margin-bottom: 0.75rem;
}

.dim {
  color: var(--mist);
  font-size: 0.82rem;
}

@media (max-width: 640px) {
  .meta-grid {
    grid-template-columns: 1fr;
  }
}
</style>
