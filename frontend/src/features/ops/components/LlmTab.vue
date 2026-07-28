<script setup lang="ts">
import { reactive, ref } from 'vue'

import {
  deleteProvider,
  getProviders,
  refreshProviderModels,
  saveProvider,
  setDefaultProvider,
  testProvider,
} from '@/shared/api/quant'
import EmptyState from '@/shared/components/ui/EmptyState.vue'
import Sheet from '@/shared/components/layout/Sheet.vue'
import { confirmDangerous } from '@/shared/lib/confirm'
import { dialogWidth } from '@/shared/lib/format'
import type { LlmProvider } from '@/shared/types/quant'
import { useOpsFeedback } from '../composables/useOpsFeedback'

const emit = defineEmits<{
  'providers-loaded': [providers: LlmProvider[]]
}>()

const { busy, notice, guard } = useOpsFeedback()

const providers = ref<LlmProvider[]>([])
const providerFormOpen = ref(false)
const providerForm = reactive({
  name: '',
  base_url: '',
  api_key: '',
  protocol: 'openai_compatible' as 'openai_compatible' | 'anthropic',
  model: '',
  proxy_url: '',
  is_default: false,
})

async function load(): Promise<void> {
  providers.value = await getProviders()
  emit('providers-loaded', providers.value)
}

async function submitProvider(): Promise<void> {
  const saved = await guard(() =>
    saveProvider({
      name: providerForm.name,
      base_url: providerForm.base_url,
      api_key: providerForm.api_key || undefined,
      protocol: providerForm.protocol,
      model: providerForm.model,
      proxy_url: providerForm.proxy_url,
      is_default: providerForm.is_default,
    }),
  )
  if (saved) {
    notice.value = `已保存 ${saved.name}，发现 ${saved.models.length} 个模型`
    providerFormOpen.value = false
    providerForm.api_key = ''
    providerForm.is_default = false
    await load()
  }
}

async function makeDefaultProvider(name: string): Promise<void> {
  const saved = await guard(() => setDefaultProvider(name))
  if (saved) {
    notice.value = `已将 ${name} 设为默认 LLM 供应商`
    await load()
  }
}

async function pullModels(name: string): Promise<void> {
  const result = await guard(() => refreshProviderModels(name))
  if (result) {
    notice.value = `${name} 已拉取 ${result.count} 个模型`
    await load()
  }
}

async function testProviderRequest(name: string): Promise<void> {
  const result = await guard(() => testProvider(name))
  if (result) {
    notice.value = `${result.provider} · ${result.model} · ${result.latency_ms} ms`
  }
}

async function setProviderModel(name: string, model: string): Promise<void> {
  const item = providers.value.find((row) => row.name === name)
  if (!item) return
  const saved = await guard(() =>
    saveProvider({
      name: item.name,
      base_url: item.base_url,
      protocol: item.protocol,
      model,
      proxy_url: item.proxy_url,
      validate_key: false,
      discover_models: false,
      is_default: item.is_default,
    }),
  )
  if (saved) {
    notice.value = `${name} 默认模型已设为 ${model}`
    await load()
  }
}

async function confirmDropProvider(name: string): Promise<void> {
  if (!(await confirmDangerous(`确定删除 LLM 供应商「${name}」？`, '确认删除', '删除'))) return
  await guard(() => deleteProvider(name), `已删除 ${name}`)
  await load()
}

defineExpose({ load, providers })
</script>

<template>
  <Sheet title="LLM 供应商" :chip="providers.length">
    <template #actions>
      <el-button type="primary" link @click="providerFormOpen = true">添加</el-button>
    </template>

    <div v-if="providers.length" class="provider-grid">
      <article
        v-for="item in providers"
        :key="item.id"
        class="provider-card"
        :class="{ 'is-default': item.is_default }"
      >
        <header class="provider-card-head">
          <div>
            <strong>{{ item.name }}</strong>
            <span v-if="item.is_default" class="tag default-tag">默认</span>
            <span class="tag">{{ item.protocol === 'anthropic' ? 'Anthropic' : 'OpenAI 兼容' }}</span>
          </div>
          <span class="mono dim">密钥 ···{{ item.key_last4 || '未设' }}</span>
        </header>
        <p class="provider-url mono dim">{{ item.base_url }}</p>
        <div class="provider-fields">
          <label>
            <span>默认模型</span>
            <el-select
              :model-value="item.default_model"
              filterable
              allow-create
              default-first-option
              placeholder="先拉取模型"
              class="full"
              :disabled="busy"
              @change="(value: string) => setProviderModel(item.name, value)"
            >
              <el-option v-for="model in item.models" :key="model" :label="model" :value="model" />
            </el-select>
          </label>
          <div class="provider-meta">
            <span>{{ item.models.length }} 个模型</span>
            <span v-if="item.models_synced_at" class="dim">
              {{ item.models_synced_at.replace('T', ' ').slice(0, 16) }}
            </span>
          </div>
        </div>
        <div class="provider-actions">
          <el-button size="small" type="primary" plain :loading="busy" @click="pullModels(item.name)">
            拉取模型
          </el-button>
          <el-button size="small" plain :loading="busy" @click="testProviderRequest(item.name)">
            测试请求
          </el-button>
          <el-button
            v-if="!item.is_default"
            size="small"
            :disabled="busy"
            @click="makeDefaultProvider(item.name)"
          >
            设为默认
          </el-button>
          <el-button
            size="small"
            text
            type="danger"
            :disabled="busy"
            @click="confirmDropProvider(item.name)"
          >
            删除
          </el-button>
        </div>
      </article>
    </div>
    <EmptyState v-else description="尚未配置。服务器实测 OpenRouter 与 DeepSeek 直连可达、无需代理。" />
    <p class="form-hint">
      同一供应商可在量化选股、策略转换等处分别选择模型和思考程度，不必为每次调用新建供应商。
    </p>
  </Sheet>

  <el-dialog
    v-model="providerFormOpen"
    title="添加 LLM 供应商"
    :width="dialogWidth()"
    destroy-on-close
  >
    <el-form label-position="top" @submit.prevent="submitProvider">
      <div class="form-grid">
        <el-form-item label="名称" required>
          <el-input v-model.trim="providerForm.name" placeholder="openrouter" />
        </el-form-item>
        <el-form-item label="协议">
          <el-select v-model="providerForm.protocol" class="full">
            <el-option label="OpenAI 兼容" value="openai_compatible" />
            <el-option label="Anthropic" value="anthropic" />
          </el-select>
        </el-form-item>
        <el-form-item label="Base URL" required class="full-span">
          <el-input
            v-model.trim="providerForm.base_url"
            placeholder="https://openrouter.ai/api/v1"
          />
        </el-form-item>
        <el-form-item label="API Key">
          <el-input
            v-model.trim="providerForm.api_key"
            type="password"
            autocomplete="off"
            show-password
          />
        </el-form-item>
        <el-form-item label="默认模型">
          <el-input v-model.trim="providerForm.model" placeholder="留空则自动取列表第一个" />
        </el-form-item>
        <el-form-item label="专用代理" class="full-span">
          <el-input
            v-model.trim="providerForm.proxy_url"
            placeholder="境外供应商填 http://172.17.0.1:7890"
          />
        </el-form-item>
        <el-form-item class="full-span">
          <el-checkbox v-model="providerForm.is_default">设为默认</el-checkbox>
        </el-form-item>
      </div>
      <p class="form-hint">
        保存时会发一次最小请求验证 Key 是否可用，校验不过不会落库。密钥用 AES-256-GCM 加密存储，
        任何接口只回末四位。
      </p>
    </el-form>
    <template #footer>
      <el-button @click="providerFormOpen = false">取消</el-button>
      <el-button type="primary" :disabled="busy" @click="submitProvider">保存并校验</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.provider-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(18rem, 1fr));
  gap: 0.75rem;
  padding: 0.85rem;
}

.provider-card {
  display: flex;
  flex-direction: column;
  gap: 0.55rem;
  padding: 0.85rem 0.9rem;
  border: 1px solid var(--rule);
  border-radius: var(--radius);
  background: var(--sheet);
}

.provider-card.is-default {
  border-color: color-mix(in srgb, var(--seal) 35%, var(--rule));
  background: color-mix(in srgb, var(--seal-soft) 55%, var(--sheet));
}

.provider-card-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 0.5rem;
}

.provider-card-head strong {
  margin-right: 0.35rem;
}

.provider-url {
  margin: 0;
  font-size: 0.75rem;
  word-break: break-all;
}

.provider-fields {
  display: grid;
  gap: 0.35rem;
}

.provider-fields label {
  display: grid;
  gap: 0.25rem;
  font-size: 0.78rem;
  color: var(--mist);
}

.provider-meta {
  display: flex;
  justify-content: space-between;
  gap: 0.5rem;
  font-size: 0.75rem;
  color: var(--ink);
}

.provider-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem;
  padding-top: 0.25rem;
  border-top: 1px dashed var(--rule);
}
</style>
