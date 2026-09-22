<script setup lang="ts">
import { default as DialogPanel } from '@/shared/components/ui/app/DialogPanel.vue'
import { default as FormLayout } from '@/shared/components/ui/app/FormLayout.vue'
import { default as ToggleSwitch } from '@/shared/components/ui/app/ToggleSwitch.vue'
import { default as FormField } from '@/shared/components/ui/app/FormField.vue'
import { default as TextField } from '@/shared/components/ui/app/TextField.vue'
import { StatusBadge } from '@/shared/components/ui/app/presentation'
import { default as ChoiceField } from '@/shared/components/ui/app/ChoiceField.vue'
import { default as ChoiceOption } from '@/shared/components/ui/app/ChoiceOption.vue'
import { default as HintTooltip } from '@/shared/components/ui/app/HintTooltip.vue'
import { default as ActionButton } from '@/shared/components/ui/app/ActionButton.vue'

import { computed, reactive, ref, watch } from 'vue'

import EmptyState from '@/shared/components/ui/EmptyState.vue'
import { formatContextWindow } from '@/shared/lib/llm'
import type { LlmProvider } from '@/shared/types/quant'

export type ProviderFormPayload = {
  name: string
  base_url: string
  api_key?: string
  protocol: 'openai_compatible' | 'anthropic'
  model: string
  proxy_url: string
  note: string
  is_default: boolean
  validate_key: boolean
  discover_models: boolean
}

const props = defineProps<{
  open: boolean
  busy?: boolean
  /** null = 添加；有值 = 编辑 */
  provider: LlmProvider | null
}>()

const emit = defineEmits<{
  'update:open': [value: boolean]
  save: [payload: ProviderFormPayload]
  test: []
  catalog: []
}>()

const visible = computed({
  get: () => props.open,
  set: (value: boolean) => emit('update:open', value),
})

const isEdit = computed(() => Boolean(props.provider))

const title = computed(() =>
  isEdit.value ? `编辑 ${props.provider!.name}` : '添加供应商',
)

const dialogWidth = computed(() => {
  if (typeof window !== 'undefined' && window.innerWidth <= 760) return '94vw'
  return '52rem'
})

const form = reactive({
  name: '',
  note: '',
  base_url: '',
  api_key: '',
  protocol: 'openai_compatible' as 'openai_compatible' | 'anthropic',
  model: '',
  proxy_url: '',
  is_default: false,
})

const advancedOpen = ref(false)

watch(
  () => [props.open, props.provider] as const,
  ([open, provider]) => {
    if (!open) return
    if (provider) {
      form.name = provider.name
      form.note = provider.note || ''
      form.base_url = provider.base_url
      form.api_key = ''
      form.protocol = provider.protocol
      form.model = provider.default_model || ''
      form.proxy_url = provider.proxy_url || ''
      form.is_default = provider.is_default
      advancedOpen.value = Boolean(provider.proxy_url)
    } else {
      form.name = ''
      form.note = ''
      form.base_url = ''
      form.api_key = ''
      form.protocol = 'openai_compatible'
      form.model = ''
      form.proxy_url = ''
      form.is_default = false
      advancedOpen.value = false
    }
  },
  { immediate: true },
)

const previewRows = computed(() => {
  const catalog = props.provider?.model_catalog ?? []
  if (!catalog.length) return []
  const def = props.provider?.default_model || ''
  const ordered = [...catalog].sort((a, b) => {
    if (a.id === def) return -1
    if (b.id === def) return 1
    if (a.enabled !== b.enabled) return a.enabled ? -1 : 1
    return a.id.localeCompare(b.id)
  })
  return ordered.slice(0, 5).map((row) => ({
    id: row.id,
    badge: row.id === def ? '默认' : row.enabled ? '启用' : '停用',
    ctx: formatContextWindow(row.context_window) || '—',
    isDefault: row.id === def,
  }))
})

const catalogStats = computed(() => {
  const p = props.provider
  if (!p) return null
  const total = p.model_catalog?.length ?? p.models.length
  return { enabled: p.models.length, total }
})

const keyConfigured = computed(() => Boolean(props.provider?.has_key))

function submit(): void {
  const name = form.name.trim()
  const base_url = form.base_url.trim()
  if (!name || !base_url) return
  emit('save', {
    name,
    base_url,
    api_key: form.api_key.trim() || undefined,
    protocol: form.protocol,
    model: form.model.trim(),
    proxy_url: form.proxy_url.trim(),
    note: form.note.trim(),
    is_default: form.is_default,
    validate_key: false,
    discover_models: false,
  })
}
</script>

<template>
  <DialogPanel
    v-model="visible"
    :title="title"
    :width="dialogWidth"
    destroy-on-close
    align-center
    class="llm-provider-dialog ops-dialog"
    @closed="form.api_key = ''"
  >
    <p v-if="isEdit" class="dialog-sub mono">名称即线路 id，已有引用不会断</p>

    <FormLayout label-position="top" class="dlg-form" @submit.prevent="submit">
      <div class="dlg-layout">
        <div class="dlg-main">
          <section class="sec">
            <header class="sec__head">
              <span class="sec__title">身份</span>
              <ToggleSwitch
                v-model="form.is_default"
                aria-label="设为默认供应商"
                :disabled="busy"
                size="small"
                inline-prompt
                active-text="默认"
                inactive-text="普通"
              />
            </header>
            <div class="sec__body form-grid">
              <FormField label="显示名称" required>
                <TextField
                  v-model.trim="form.name"
                  placeholder="openrouter"
                  :disabled="isEdit || busy"
                />
              </FormField>
              <FormField label="备注">
                <TextField
                  v-model.trim="form.note"
                  placeholder="例如：选股 / 复盘主线"
                  :disabled="busy"
                />
              </FormField>
            </div>
          </section>

          <section class="sec">
            <header class="sec__head">
              <span class="sec__title">接入</span>
              <StatusBadge
                v-if="isEdit"
                size="small"
                :tone="keyConfigured ? 'success' : 'info'"
                effect="plain"
              >
                {{ keyConfigured ? '密钥已配置' : '密钥未设' }}
              </StatusBadge>
            </header>
            <div class="sec__body form-grid">
              <FormField label="协议">
                <ChoiceField v-model="form.protocol" class="full" :disabled="busy">
                  <ChoiceOption label="OpenAI 兼容" value="openai_compatible" />
                  <ChoiceOption label="Anthropic" value="anthropic" />
                </ChoiceField>
              </FormField>
              <FormField label="默认模型">
                <TextField
                  v-model.trim="form.model"
                  placeholder="模型 ID，可稍后配置"
                  :disabled="busy"
                />
              </FormField>
              <FormField label="Base URL" required>
                <!-- 「填服务端点，不是官网首页」原来是块尾一行常驻说明，挪到这个输入框上 -->
                <HintTooltip placement="top-start" content="填服务端点（.../v1），不是官网首页">
                  <TextField
                    v-model.trim="form.base_url"
                    placeholder="https://openrouter.ai/api/v1"
                    :disabled="busy"
                  />
                </HintTooltip>
              </FormField>
              <FormField :label="isEdit ? 'API Key（留空保持）' : 'API Key'">
                <TextField
                  v-model.trim="form.api_key"
                  type="password"
                  autocomplete="off"
                  show-password
                  :placeholder="isEdit ? '留空则不改' : 'sk-…'"
                  :disabled="busy"
                />
              </FormField>
              <FormField v-if="advancedOpen || form.proxy_url" label="专用代理" class="full-span">
                <TextField
                  v-model.trim="form.proxy_url"
                  placeholder="http://127.0.0.1:7890"
                  :disabled="busy"
                />
              </FormField>
              <div v-else class="adv full-span">
                <ActionButton variant="link" tone="info" @click="advancedOpen = true">+ 专用代理</ActionButton>
              </div>
            </div>
          </section>
        </div>

        <aside class="dlg-side sec">
          <header class="sec__head">
            <span class="sec__title">模型目录</span>
            <span v-if="catalogStats" class="sec__stat mono">
              {{ catalogStats.enabled }}/{{ catalogStats.total }}
            </span>
          </header>
          <div class="sec__body side-body">
            <template v-if="isEdit">
              <div v-if="previewRows.length" class="preview-table">
                <div
                  v-for="row in previewRows"
                  :key="row.id"
                  class="preview-row"
                  :class="{ 'is-default': row.isDefault }"
                >
                  <span class="preview-id mono">{{ row.id }}</span>
                  <span class="preview-badge" :class="{ seal: row.isDefault }">{{ row.badge }}</span>
                  <span class="preview-ctx mono">{{ row.ctx }}</span>
                </div>
              </div>
              <EmptyState v-else description="目录为空" reason="点下方「打开完整目录」拉一次" />
              <ActionButton
                class="side-cta"
                :disabled="busy"
                @click="emit('catalog')"
              >
                打开完整目录
              </ActionButton>
            </template>
            <EmptyState
              v-else
              description="还没有模型目录"
              reason="保存后可按需拉取模型"
            />
          </div>
        </aside>
      </div>
    </FormLayout>

    <template #footer>
      <ActionButton access="read" :disabled="busy" @click="visible = false">取消</ActionButton>
      <ActionButton v-if="isEdit" :busy="busy" @click="emit('test')">测试连接</ActionButton>
      <!-- 「改动何时生效」原是表单末尾的常驻说明段，挪到它描述的那颗保存按钮上 -->
      <HintTooltip
        placement="top-end"
        content="改动对新请求立即生效；进行中的选股 / Agent 会话需重连后换线"
        :disabled="!isEdit"
      >
        <ActionButton tone="primary" :busy="busy" @click="submit">
          保存
        </ActionButton>
      </HintTooltip>
    </template>
  </DialogPanel>
</template>

<style scoped>
.dialog-sub {
  margin: -0.25rem 0 0.55rem;
  font-size: var(--fs-kicker);
  color: var(--mist);
}

.dlg-form {
  margin: 0;
}

.dlg-layout {
  display: grid;
  grid-template-columns: minmax(0, 1.45fr) minmax(14rem, 0.9fr);
  gap: 0.7rem;
  align-items: stretch;
}

.dlg-main {
  display: flex;
  flex-direction: column;
  gap: 0.7rem;
  min-width: 0;
}

.dlg-side {
  min-width: 0;
  display: flex;
  flex-direction: column;
}

.sec {
  border: 1px solid var(--rule);
  border-radius: var(--radius);
  overflow: hidden;
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
  font-size: 0.76rem;
  font-weight: 650;
  color: var(--ink);
  letter-spacing: 0.02em;
}

.sec__stat {
  font-size: var(--fs-kicker);
  color: var(--mist);
}

.sec__body {
  padding: 0.35rem 0.65rem 0;
}

.form-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 12rem), 1fr));
  gap: 0 var(--gap-2);
}

.form-grid .full-span {
  grid-column: 1 / -1;
}

.full {
  width: 100%;
}

.adv {
  padding: 0 0 0.45rem;
}

.side-body {
  display: flex;
  flex-direction: column;
  flex: 1;
  padding-bottom: 0.55rem;
  min-height: 0;
}

.side-cta {
  margin-top: auto;
  width: 100%;
}

.preview-table {
  border: 1px solid var(--rule);
  border-radius: 6px;
  overflow: hidden;
  margin-bottom: 0.5rem;
}

.preview-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto auto;
  gap: 0.4rem;
  padding: 0.3rem 0.45rem;
  font-size: var(--fs-kicker);
  border-top: 1px solid var(--rule);
  color: var(--ink);
  background: var(--sheet);
}

.preview-row:first-child {
  border-top: none;
}

.preview-row.is-default {
  background: color-mix(in oklab, var(--seal-soft) 55%, var(--sheet));
}

.preview-id {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.preview-badge {
  color: var(--mist);
}

.preview-badge.seal {
  color: var(--seal-ink);
  font-weight: 600;
}

.preview-ctx {
  color: var(--mist);
}

/* 前缀限本弹窗：裸 deep 会污染全站 dialog */
:deep(.llm-provider-dialog .form-field) {
  margin-bottom: var(--gap-2);
}

:deep(.llm-provider-dialog .form-field__label) {
  margin-bottom: var(--gap-1);
}

@media (max-width: 760px) {
  .dlg-layout {
    grid-template-columns: 1fr;
  }

  .form-grid {
    grid-template-columns: 1fr;
  }
}
</style>
<style scoped src="./OpsDialogSurface.css"></style>
