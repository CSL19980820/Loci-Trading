<script setup lang="ts">
import { ref } from 'vue'
import { ElMessage } from 'element-plus'

import {
  confirmQianlongImport,
  previewQianlongImport,
  type QianlongImportPreview,
} from '@/shared/api/palace'
import { money, signedMoney } from '@/shared/lib/format'

const model = defineModel<boolean>({ default: false })
const emit = defineEmits<{ saved: [] }>()

const step = ref(1)
const selectedFile = ref<File | null>(null)
const preview = ref<QianlongImportPreview | null>(null)
const loading = ref(false)
const error = ref('')
const fileInput = ref<HTMLInputElement | null>(null)

function onFileChange(event: Event): void {
  const input = event.target as HTMLInputElement
  selectedFile.value = input.files?.[0] ?? null
  error.value = ''
}

function reset(): void {
  step.value = 1
  selectedFile.value = null
  preview.value = null
  loading.value = false
  error.value = ''
  if (fileInput.value) fileInput.value.value = ''
}

function close(): void {
  model.value = false
}

async function previewFile(): Promise<void> {
  if (!selectedFile.value) return
  loading.value = true
  error.value = ''
  try {
    preview.value = await previewQianlongImport(selectedFile.value)
    step.value = 2
  } catch (caught: unknown) {
    error.value = caught instanceof Error ? caught.message : '预览失败'
  } finally {
    loading.value = false
  }
}

async function confirmImport(): Promise<void> {
  if (!selectedFile.value || !preview.value?.can_import) return
  loading.value = true
  error.value = ''
  try {
    await confirmQianlongImport(selectedFile.value)
    ElMessage.success('state 已导入')
    emit('saved')
    close()
  } catch (caught: unknown) {
    error.value = caught instanceof Error ? caught.message : '导入失败'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <el-dialog
    v-model="model"
    title="导入潜龙快照"
    width="40rem"
    destroy-on-close
    @closed="reset"
  >
    <template v-if="step === 1">
      <p class="hint">选择潜龙技能的快照文件（JSON），先预览再确认导入。</p>
      <div class="file-row">
        <label class="upload-label">
          <el-button type="primary" plain tag="span">选择 JSON 文件</el-button>
          <input
            ref="fileInput"
            type="file"
            accept=".json,application/json"
            hidden
            @change="onFileChange"
          />
        </label>
        <span v-if="selectedFile" class="file-name">{{ selectedFile.name }}</span>
        <span v-else class="file-name muted">未选择文件</span>
      </div>
      <el-alert v-if="error" :title="error" type="error" show-icon :closable="false" class="mt" />
    </template>

    <template v-else>
      <el-alert
        v-if="preview && !preview.can_import"
        :title="preview.block_reason"
        type="warning"
        show-icon
        :closable="false"
        class="mb"
      />
      <dl v-if="preview" class="summary">
        <div><dt>快照日期</dt><dd>{{ preview.date || '—' }}</dd></div>
        <div><dt>持仓数</dt><dd>{{ preview.holdings_count }}</dd></div>
        <div><dt>已实现盈亏基线</dt><dd>{{ signedMoney(preview.realized_pnl_baseline) }}</dd></div>
        <div><dt>总资产</dt><dd>{{ preview.total_assets != null ? money(preview.total_assets) : '—' }}</dd></div>
      </dl>
      <el-table v-if="preview?.holdings.length" :data="preview.holdings" size="small" max-height="240">
        <el-table-column label="代码" prop="code" width="90" />
        <el-table-column label="名称" prop="name" min-width="100" />
        <el-table-column label="数量" align="right" width="90">
          <template #default="{ row }">{{ row.shares.toLocaleString('zh-CN') }}</template>
        </el-table-column>
        <el-table-column label="成本" align="right" width="90">
          <template #default="{ row }">{{ row.cost.toFixed(3) }}</template>
        </el-table-column>
        <el-table-column label="备注" prop="note" min-width="120" show-overflow-tooltip />
      </el-table>
      <el-alert v-if="error" :title="error" type="error" show-icon :closable="false" class="mt" />
    </template>

    <template #footer>
      <el-button v-if="step === 2" @click="step = 1">上一步</el-button>
      <el-button @click="close">取消</el-button>
      <el-button v-if="step === 1" type="primary" :loading="loading" :disabled="!selectedFile" @click="previewFile">
        预览
      </el-button>
      <el-button
        v-else
        type="primary"
        :loading="loading"
        :disabled="!preview?.can_import"
        @click="confirmImport"
      >
        确认导入
      </el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.hint {
  margin: 0 0 0.75rem;
  color: var(--muted);
  font-size: 0.9rem;
}

.file-row {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  flex-wrap: wrap;
}

.upload-label {
  display: inline-flex;
  cursor: pointer;
  margin: 0;
}

.file-name {
  font-size: 0.88rem;
  color: var(--ink);
  word-break: break-all;
}

.file-name.muted {
  color: var(--muted);
}

.summary {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0.5rem 1rem;
  margin: 0 0 0.75rem;
}

.summary div {
  display: flex;
  gap: 0.5rem;
}

.summary dt {
  color: var(--muted);
  min-width: 6rem;
}

.summary dd {
  margin: 0;
}

.mt {
  margin-top: 0.75rem;
}

.mb {
  margin-bottom: 0.75rem;
}
</style>
