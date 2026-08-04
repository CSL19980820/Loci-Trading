<script setup lang="ts">
import Sheet from '@/shared/components/layout/Sheet.vue'

import type { ScreenSkillDraftModel } from '../composables/screenSkillDraft'

const props = defineProps<{
  draft: ScreenSkillDraftModel
}>()

const emit = defineEmits<{
  addLogic: []
  removeLogic: [index: number]
}>()
</script>

<template>
  <Sheet title="逻辑说明" padded margin>
    <div class="meta-grid">
      <el-form-item label="Slug" required>
        <el-input v-model.trim="props.draft.slug" maxlength="64" placeholder="my-breakout" />
      </el-form-item>
      <el-form-item label="名称" required>
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
      <el-form-item label="最少 K 线">
        <el-input-number v-model="props.draft.minBars" :min="1" :max="1000" :controls="false" class="full" />
      </el-form-item>
      <el-form-item label="主信号名" required>
        <el-input v-model.trim="props.draft.signal" maxlength="32" placeholder="PICK" />
      </el-form-item>
      <el-form-item label="运行时">
        <el-input :model-value="props.draft.runtime === 'python' ? 'Python' : '公式'" readonly />
      </el-form-item>
    </div>

    <el-form-item label="说明">
      <el-input
        v-model.trim="props.draft.description"
        type="textarea"
        :rows="3"
        maxlength="240"
        placeholder="说明入选逻辑、适用阶段、风险与禁用场景。"
      />
    </el-form-item>

    <el-form-item label="因子清单">
      <el-input
        v-model="props.draft.factorsText"
        type="textarea"
        :rows="2"
        placeholder="用逗号或换行分隔，例如 BASE_MA, VOL_RATIO, BREAKOUT"
      />
    </el-form-item>

    <div class="section-head">
      <div>
        <strong>逻辑卡片</strong>
        <div class="dim">每条逻辑单独记录表达式、解释与引用 ID。</div>
      </div>
      <el-button size="small" @click="emit('addLogic')">新增逻辑</el-button>
    </div>

    <div class="logic-list">
      <el-card v-for="(row, index) in props.draft.logic" :key="row.id" shadow="never" class="logic-card">
        <template #header>
          <div class="logic-card__head">
            <span>{{ row.id || `逻辑 ${index + 1}` }}</span>
            <el-button text type="danger" size="small" @click="emit('removeLogic', index)">删除</el-button>
          </div>
        </template>
        <div class="meta-grid">
          <el-form-item label="逻辑 ID" required>
            <el-input v-model.trim="row.id" maxlength="40" placeholder="logic_breakout" />
          </el-form-item>
          <el-form-item label="标题" required>
            <el-input v-model.trim="row.title" maxlength="64" placeholder="站上均线" />
          </el-form-item>
        </div>
        <el-form-item label="表达式" required>
          <el-input
            v-model.trim="row.expression"
            type="textarea"
            :rows="2"
            placeholder="例如 CLOSE > MA(CLOSE, N)"
          />
        </el-form-item>
        <el-form-item label="解释">
          <el-input
            v-model.trim="row.explanation"
            type="textarea"
            :rows="3"
            placeholder="说明该逻辑为何存在、适用什么行情。"
          />
        </el-form-item>
        <el-form-item label="引用 ID">
          <el-input
            v-model="row.citationsText"
            type="textarea"
            :rows="2"
            placeholder="逗号或换行分隔，例如 ref_ma_handbook, ref_turnover_note"
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
