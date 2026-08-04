<script setup lang="ts">
import Sheet from '@/shared/components/layout/Sheet.vue'

import type { ScreenSkillDraftModel } from '../composables/screenSkillDraft'

const props = defineProps<{
  draft: ScreenSkillDraftModel
}>()

const emit = defineEmits<{
  addReference: []
  removeReference: [index: number]
}>()
</script>

<template>
  <Sheet title="资料来源" padded margin>
    <div class="section-head">
      <div>
        <strong>引用台账</strong>
        <div class="dim">逻辑里的 citation 必须引用这里的 ID，建议写到链接/路径/引文级别。</div>
      </div>
      <el-button size="small" @click="emit('addReference')">新增资料</el-button>
    </div>

    <div class="reference-list">
      <el-card v-for="(row, index) in props.draft.references" :key="row.id" shadow="never" class="reference-card">
        <template #header>
          <div class="reference-card__head">
            <span>{{ row.id || `资料 ${index + 1}` }}</span>
            <el-button text type="danger" size="small" @click="emit('removeReference', index)">删除</el-button>
          </div>
        </template>

        <div class="meta-grid">
          <el-form-item label="资料 ID" required>
            <el-input v-model.trim="row.id" maxlength="48" placeholder="ref_ma_handbook" />
          </el-form-item>
          <el-form-item label="标题" required>
            <el-input v-model.trim="row.title" maxlength="80" placeholder="均线手册 / 研报 / 笔记标题" />
          </el-form-item>
          <el-form-item label="类型" required>
            <el-select v-model="row.kind" allow-create filterable default-first-option class="full">
              <el-option label="report" value="report" />
              <el-option label="doc" value="doc" />
              <el-option label="paper" value="paper" />
              <el-option label="note" value="note" />
              <el-option label="code" value="code" />
            </el-select>
          </el-form-item>
          <el-form-item label="URL">
            <el-input v-model.trim="row.url" placeholder="https://..." />
          </el-form-item>
          <el-form-item label="本地路径">
            <el-input v-model.trim="row.path" placeholder="docs/strategy/breakout.md" />
          </el-form-item>
          <el-form-item label="章节 / 页码">
            <el-input v-model.trim="row.section" placeholder="第 2 节 / P8-P10" />
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
