<script setup lang="ts">
import { computed } from 'vue'

import type { LlmProvider } from '@/shared/types/quant'

const props = defineProps<{
  provider: LlmProvider
  busy?: boolean
}>()

const emit = defineEmits<{
  edit: []
  'set-default': []
  catalog: []
  pull: []
  test: []
  remove: []
}>()

const protocolLabel = computed(() =>
  props.provider.protocol === 'anthropic' ? 'Anthropic' : 'OpenAI 兼容',
)

const protocolShort = computed(() =>
  props.provider.protocol === 'anthropic' ? 'anthropic' : 'openai',
)

const host = computed(() => {
  try {
    return new URL(props.provider.base_url).host
  } catch {
    return props.provider.base_url.replace(/^https?:\/\//, '').split('/')[0] || props.provider.base_url
  }
})

const keyLabel = computed(() =>
  props.provider.key_last4 ? `···${props.provider.key_last4}` : '未设',
)

const catalogTotal = computed(
  () => props.provider.model_catalog?.length ?? props.provider.models.length,
)

const enabledCount = computed(() => props.provider.models.length)

const chips = computed(() => {
  const catalog = props.provider.model_catalog ?? []
  const enabled = catalog.filter((m) => m.enabled)
  const pool = enabled.length ? enabled.map((m) => m.id) : props.provider.models
  const def = props.provider.default_model
  const ordered = def && pool.includes(def) ? [def, ...pool.filter((id) => id !== def)] : pool
  return ordered.slice(0, 3)
})

const extraCount = computed(() => Math.max(0, catalogTotal.value - chips.value.length))

const initial = computed(() => (props.provider.name.slice(0, 1) || '?').toUpperCase())

function onMore(command: string): void {
  if (command === 'catalog') emit('catalog')
  else if (command === 'pull') emit('pull')
  else if (command === 'test') emit('test')
  else if (command === 'remove') emit('remove')
}
</script>

<template>
  <article
    class="prov-card"
    :class="{ 'is-default': provider.is_default }"
    role="button"
    tabindex="0"
    @click="emit('edit')"
    @keydown.enter.prevent="emit('edit')"
  >
    <header class="prov-card__head">
      <span class="prov-card__avatar" aria-hidden="true">{{ initial }}</span>
      <div class="prov-card__identity">
        <div class="prov-card__title-row">
          <strong class="prov-card__name">{{ provider.name }}</strong>
          <el-tag v-if="provider.is_default" size="small" type="danger" effect="plain">默认</el-tag>
          <el-tag v-if="!provider.has_key" size="small" type="info" effect="plain">缺密钥</el-tag>
        </div>
        <p class="prov-card__meta">{{ protocolLabel }}</p>
      </div>
      <el-dropdown trigger="click" :disabled="busy" @command="onMore" @click.stop>
        <el-button
          text
          circle
          size="small"
          :disabled="busy"
          aria-label="更多操作"
          @click.stop
        >
          ···
        </el-button>
        <template #dropdown>
          <el-dropdown-menu>
            <el-dropdown-item command="catalog">模型目录</el-dropdown-item>
            <el-dropdown-item command="pull">拉取模型</el-dropdown-item>
            <el-dropdown-item command="test">测试连接</el-dropdown-item>
            <el-dropdown-item divided command="remove" class="danger-item">删除</el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>
    </header>

    <div class="endpoint-strip" :title="provider.base_url">
      <span class="endpoint-strip__proto">{{ protocolShort }}</span>
      <span class="endpoint-strip__dot" aria-hidden="true">·</span>
      <span class="endpoint-strip__host">{{ host }}</span>
      <span class="endpoint-strip__dot" aria-hidden="true">·</span>
      <span class="endpoint-strip__key" :class="{ ok: provider.has_key }">{{ keyLabel }}</span>
    </div>

    <div v-if="chips.length" class="prov-card__chips">
      <span
        v-for="(id, i) in chips"
        :key="id"
        class="model-chip"
        :class="{ active: id === provider.default_model || (!provider.default_model && i === 0) }"
      >
        {{ id }}
      </span>
      <span v-if="extraCount > 0" class="prov-card__extra mono">+{{ extraCount }}</span>
    </div>
    <p v-else class="prov-card__empty">尚未拉取模型</p>

    <footer class="prov-card__foot" @click.stop>
      <span class="prov-card__count mono">{{ enabledCount }}/{{ catalogTotal }} 启用</span>
      <div class="prov-card__actions">
        <el-button
          v-if="!provider.is_default"
          link
          class="set-default"
          :disabled="busy"
          @click="emit('set-default')"
        >
          设为默认
        </el-button>
        <span v-else class="prov-card__default-hint">当前默认</span>
        <el-button link :disabled="busy" @click="emit('edit')">编辑</el-button>
      </div>
    </footer>
  </article>
</template>

<style scoped>
.prov-card {
  display: flex;
  flex-direction: column;
  gap: 0.55rem;
  min-height: 10.5rem;
  padding: 0.7rem 0.75rem;
  background: var(--sheet);
  border: 1px solid var(--rule);
  border-radius: 8px;
  cursor: pointer;
  transition: border-color 0.12s ease, background 0.12s ease;
}

.prov-card:hover,
.prov-card:focus-visible {
  border-color: color-mix(in srgb, var(--ink) 28%, var(--rule));
  outline: none;
}

.prov-card.is-default {
  border-color: var(--seal);
  background: color-mix(in srgb, var(--seal-soft) 35%, var(--sheet));
}

.prov-card__head {
  display: flex;
  align-items: flex-start;
  gap: 0.55rem;
}

.prov-card__avatar {
  flex: 0 0 auto;
  width: 2.1rem;
  height: 2.1rem;
  display: grid;
  place-items: center;
  border-radius: 8px;
  font-family: var(--font-display);
  font-weight: 700;
  font-size: 0.95rem;
  color: var(--ink);
  background: var(--panel-2);
  border: 1px solid var(--rule);
}

.prov-card.is-default .prov-card__avatar {
  color: var(--seal);
  background: var(--seal-soft);
  border-color: var(--seal);
}

.prov-card__identity {
  flex: 1 1 auto;
  min-width: 0;
}

.prov-card__title-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.3rem;
}

.prov-card__name {
  font-size: 0.9rem;
  font-weight: 650;
  color: var(--ink);
}

.prov-card__meta {
  margin: 0.1rem 0 0;
  font-size: 0.72rem;
  color: var(--mist);
}

.endpoint-strip {
  display: flex;
  align-items: center;
  gap: 0;
  min-width: 0;
  padding: 0.28rem 0.45rem;
  border: 1px solid var(--rule);
  border-radius: 4px;
  background: var(--panel-2);
  font-family: var(--mono);
  font-size: 0.7rem;
  line-height: 1.35;
  color: var(--mist);
  overflow: hidden;
}

.endpoint-strip__proto {
  color: var(--mist);
  flex: 0 0 auto;
}

.endpoint-strip__dot {
  margin: 0 0.35rem;
  color: var(--rule);
  flex: 0 0 auto;
}

.endpoint-strip__host {
  color: var(--ink);
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  min-width: 0;
}

.endpoint-strip__key {
  color: var(--mist);
  flex: 0 0 auto;
}

.endpoint-strip__key.ok {
  color: var(--lake);
}

.prov-card__chips {
  display: flex;
  flex-wrap: wrap;
  gap: 0.25rem;
  align-items: center;
}

.model-chip {
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  padding: 0.1rem 0.4rem;
  border-radius: 3px;
  border: 1px solid var(--rule);
  background: var(--sheet);
  font-family: var(--mono);
  font-size: 0.66rem;
  color: var(--mist);
}

.model-chip.active {
  border-color: var(--seal);
  background: var(--seal-soft);
  color: var(--seal);
}

.prov-card__extra {
  font-size: 0.66rem;
  color: var(--mist);
}

.prov-card__empty {
  margin: 0;
  font-size: 0.72rem;
  color: var(--mist);
}

.prov-card__foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
  margin-top: auto;
  padding-top: 0.4rem;
  border-top: 1px solid var(--rule);
}

.prov-card__count {
  font-size: 0.7rem;
  color: var(--mist);
}

.prov-card__actions {
  display: flex;
  align-items: center;
  gap: 0.15rem;
}

.prov-card__default-hint {
  font-size: 0.78rem;
  color: var(--mist);
  padding: 0 0.35rem;
}

.set-default {
  color: var(--lake);
}

.set-default:hover {
  color: var(--lake);
}

:deep(.danger-item) {
  color: var(--el-color-danger);
}
</style>
