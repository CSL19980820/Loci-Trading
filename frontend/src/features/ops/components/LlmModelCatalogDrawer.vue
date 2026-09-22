<script setup lang="ts">
import { default as SidePanel } from '@/shared/components/ui/app/SidePanel.vue'
import { default as ActionButton } from '@/shared/components/ui/app/ActionButton.vue'
import { default as ChoiceField } from '@/shared/components/ui/app/ChoiceField.vue'
import { default as ChoiceOption } from '@/shared/components/ui/app/ChoiceOption.vue'
import { default as DataGrid } from '@/shared/components/ui/app/DataGrid.vue'
import { default as DataColumn } from '@/shared/components/ui/app/DataColumn.vue'
import { default as ToggleSwitch } from '@/shared/components/ui/app/ToggleSwitch.vue'
import { StatusBadge } from '@/shared/components/ui/app/presentation'
import { default as TextField } from '@/shared/components/ui/app/TextField.vue'
import { default as NumberInput } from '@/shared/components/ui/app/NumberInput.vue'

/**
 * 模型目录侧拉：64rem 通栏；表体单行 blotter（开 / id·徽标 / 展示名 / 上下文·hint / 输出 / 操作）。
 */
import { computed, reactive, ref, watch } from 'vue'

import { refreshProviderModels, updateProviderModels } from '@/shared/api/quant'
import { formatContextWindow } from '@/shared/lib/llm'
import type { LlmModel, LlmProvider } from '@/shared/types/quant'
import { useOpsFeedback } from '../composables/useOpsFeedback'

const props = defineProps<{
  provider: LlmProvider | null
  open: boolean
}>()

const emit = defineEmits<{
  'update:open': [value: boolean]
  saved: [provider: LlmProvider]
}>()

const { busy, notice, guard } = useOpsFeedback()

const draft = ref<LlmModel[]>([])
const defaultModel = ref('')
const addForm = reactive({ id: '', name: '', context_window: null as number | null })

const visible = computed({
  get: () => props.open,
  set: (value: boolean) => emit('update:open', value),
})

const title = computed(() =>
  props.provider ? `模型目录 · ${props.provider.name}` : '模型目录',
)

const enabledCount = computed(() => draft.value.filter((item) => item.enabled).length)
const enabledModels = computed(() => draft.value.filter((item) => item.enabled))

function ensureDefaultModel(): void {
  const selected = draft.value.find((item) => item.id === defaultModel.value)
  if (!selected?.enabled) defaultModel.value = enabledModels.value[0]?.id || ''
}

function hasValidDefaultModel(): boolean {
  return !defaultModel.value || enabledModels.value.some((item) => item.id === defaultModel.value)
}

watch(
  () => [props.open, props.provider] as const,
  ([open, provider]) => {
    if (!open || !provider) return
    draft.value = (provider.model_catalog ?? []).map((item) => ({ ...item }))
    defaultModel.value = provider.default_model || ''
    ensureDefaultModel()
    addForm.id = ''
    addForm.name = ''
    addForm.context_window = null
  },
  { immediate: true },
)

function ctxLabel(tokens: number | null | undefined): string {
  return formatContextWindow(tokens) || '—'
}

function rowClassName({ row }: { row: Record<string, unknown> }): string {
  return row.id === defaultModel.value ? 'is-default' : ''
}

function addManualModel(): void {
  const id = addForm.id.trim()
  if (!id) {
    notice.value = '请填写模型 id'
    return
  }
  if (draft.value.some((item) => item.id === id)) {
    notice.value = `目录里已有 ${id}`
    return
  }
  draft.value = [
    ...draft.value,
    {
      id,
      name: addForm.name.trim() || id,
      enabled: true,
      context_window: addForm.context_window,
      max_output_tokens: null,
      source: 'manual',
    },
  ]
  if (!defaultModel.value) defaultModel.value = id
  addForm.id = ''
  addForm.name = ''
  addForm.context_window = null
}

function removeModel(id: string): void {
  draft.value = draft.value.filter((item) => item.id !== id)
  ensureDefaultModel()
}

function setAsDefault(id: string): void {
  const row = draft.value.find((item) => item.id === id)
  if (!row) return
  row.enabled = true
  defaultModel.value = id
}

async function pullModels(): Promise<void> {
  if (!props.provider) return
  const result = await guard(() => refreshProviderModels(props.provider!.name))
  if (!result) return
  draft.value = result.model_catalog.map((item) => ({ ...item }))
  ensureDefaultModel()
  notice.value = `已拉取并合并 ${result.count} 个模型`
}

async function saveCatalog(): Promise<void> {
  if (!props.provider) return
  if (!hasValidDefaultModel()) {
    notice.value = '默认模型必须选择已启用的目录项'
    return
  }
  const saved = await guard(() =>
    updateProviderModels(props.provider!.name, {
      models: draft.value,
      default_model: defaultModel.value || null,
    }),
  )
  if (!saved) return
  notice.value = `${saved.name} 模型目录已保存（启用 ${saved.models.length}）`
  emit('saved', saved)
  visible.value = false
}
</script>

<template>
  <SidePanel
    v-model="visible"
    :title="title"
    size="min(64rem, 92vw)"
    destroy-on-close
    append-to-body
    class="model-catalog-drawer ops-drawer"
  >
    <template v-if="provider">
      <section class="sec">
        <header class="sec__head">
          <span class="sec__title">目录</span>
          <span class="sec__stat mono">{{ enabledCount }} / {{ draft.length }} 启用</span>
        </header>
        <div class="sec__body">
          <div class="toolbar">
            <ActionButton :busy="busy" @click="pullModels">拉取</ActionButton>
            <ChoiceField
              v-model="defaultModel"
              filterable
              clearable
              placeholder="默认模型"
              aria-label="默认模型"
              class="default-select"
              :disabled="busy"
            >
              <ChoiceOption
                v-for="item in enabledModels"
                :key="item.id"
                :label="item.id"
                :value="item.id"
              />
            </ChoiceField>
            <ActionButton tone="primary" :busy="busy" @click="saveCatalog">保存目录</ActionButton>
          </div>

          <p v-if="notice" class="notice mono">{{ notice }}</p>

          <div class="catalog-scroll">
            <DataGrid
              :data="draft"
              size="small"
              row-key="id"
              height="360"
              class="catalog-table"
              :row-class-name="rowClassName"
            >
              <DataColumn label="开" width="48" align="center">
                <template #default="{ row }">
                  <ToggleSwitch
                    v-model="row.enabled"
                    :aria-label="`启用模型 ${row.id}`"
                    size="small"
                    :disabled="busy || row.id === defaultModel"
                  />
                </template>
              </DataColumn>

              <DataColumn label="模型 id" min-width="220">
                <template #default="{ row }">
                  <div class="id-cell">
                    <strong class="mono id-cell__text" :title="row.id">{{ row.id }}</strong>
                    <StatusBadge
                      v-if="row.id === defaultModel"
                      size="small"
                      tone="primary"
                      effect="plain"
                      class="id-cell__tag"
                    >
                      默认
                    </StatusBadge>
                    <StatusBadge size="small" tone="info" effect="plain" class="id-cell__tag">
                      {{ row.source === 'manual' ? '手动' : '发现' }}
                    </StatusBadge>
                  </div>
                </template>
              </DataColumn>

              <DataColumn label="展示名" min-width="168">
                <template #default="{ row }">
                  <TextField
                    v-model.trim="row.name"
                    size="small"
                    placeholder="展示名"
                    class="cell-input"
                    :disabled="busy"
                  />
                </template>
              </DataColumn>

              <DataColumn label="上下文" width="152">
                <template #default="{ row }">
                  <div class="ctx-cell">
                    <NumberInput
                      v-model="row.context_window"
                      :min="1"
                      :controls="false"
                      size="small"
                      placeholder="tokens"
                      class="cell-input"
                      :disabled="busy"
                    />
                    <span class="ctx-hint mono">{{ ctxLabel(row.context_window) }}</span>
                  </div>
                </template>
              </DataColumn>

              <DataColumn label="输出" width="112">
                <template #default="{ row }">
                  <NumberInput
                    v-model="row.max_output_tokens"
                    :min="1"
                    :controls="false"
                    size="small"
                    placeholder="tokens"
                    class="cell-input"
                    :disabled="busy"
                  />
                </template>
              </DataColumn>

              <DataColumn label="操作" width="100" align="center" header-align="center" fixed="right">
                <template #default="{ row }">
                  <ActionButton
                    v-if="row.id !== defaultModel"
                    variant="link"
                    :disabled="busy"
                    @click="setAsDefault(row.id)"
                  >
                    默认
                  </ActionButton>
                  <span v-else class="op-placeholder">—</span>
                  <ActionButton
                    v-if="row.source === 'manual'"
                    variant="link"
                    tone="danger"
                    :disabled="busy"
                    @click="removeModel(row.id)"
                  >
                    删
                  </ActionButton>
                </template>
              </DataColumn>
            </DataGrid>
          </div>
        </div>
      </section>

      <section class="sec">
        <header class="sec__head">
          <span class="sec__title">手动添加</span>
        </header>
        <div class="sec__body">
          <div class="add-row">
            <TextField v-model.trim="addForm.id" placeholder="模型 id" :disabled="busy" />
            <TextField v-model.trim="addForm.name" placeholder="展示名（可选）" :disabled="busy" />
            <NumberInput
              v-model="addForm.context_window"
              :min="1"
              :controls="false"
              placeholder="上下文"
              :disabled="busy"
            />
            <ActionButton :disabled="busy" @click="addManualModel">添加</ActionButton>
          </div>
        </div>
      </section>
    </template>
  </SidePanel>
</template>

<style scoped>
.sec {
  border: 1px solid var(--rule);
  border-radius: var(--radius);
  overflow: hidden;
  margin-bottom: 0.7rem;
  background: var(--sheet);
}

.sec__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
  padding: var(--gap-2) var(--gap-3);
  border-bottom: 1px solid var(--rule);
  background: var(--surface-sunken);
}

.sec__title {
  font-size: var(--fs-aux);
  font-weight: 650;
  color: var(--ink);
  letter-spacing: 0.02em;
}

.sec__stat {
  font-size: var(--fs-kicker);
  color: var(--mist);
}

.sec__body {
  padding: 0.65rem 0.7rem;
}

.toolbar {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  align-items: center;
  margin-bottom: 0.65rem;
}

.default-select {
  flex: 1 1 14rem;
  min-width: 0;
}

.notice {
  margin: 0 0 0.6rem;
  color: var(--mist);
  font-size: var(--fs-aux);
}

.catalog-scroll {
  min-width: 0;
  overflow-x: auto;
}

.catalog-table {
  min-width: 960px;
}

/* 行高/配色走全局表皮肤；默认行用主色浅底描边（与全站选中行同值，不用 !important） */
.catalog-table :deep(tr.is-default > td[data-slot='table-cell']) {
  background: var(--seal-soft);
}

.id-cell {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  min-width: 0;
}

.id-cell__text {
  flex: 1 1 auto;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: var(--fs-aux);
  font-weight: 600;
}

.id-cell__tag {
  flex-shrink: 0;
}

.ctx-cell {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  min-width: 0;
}

.ctx-hint {
  flex: 0 0 1.75rem;
  color: var(--mist);
  font-size: var(--fs-kicker);
  text-align: right;
}

.cell-input {
  width: 100%;
  min-width: 0;
}

.cell-input :deep(.text-field__body),
.cell-input :deep(.number-input) {
  width: 100%;
}

.op-placeholder {
  display: inline-block;
  min-width: 2rem;
  color: var(--mist);
  font-size: var(--fs-aux);
  text-align: center;
}

.add-row {
  display: grid;
  grid-template-columns: 1.4fr 1fr 7rem auto;
  gap: 0.45rem;
  align-items: center;
}

@media (max-width: 720px) {
  .add-row {
    grid-template-columns: 1fr;
  }
}
</style>
<style scoped src="./OpsDialogSurface.css"></style>
