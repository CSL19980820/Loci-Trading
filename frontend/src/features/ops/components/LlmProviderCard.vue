<script setup lang="ts">
import { Ellipsis, KeyRound } from '@lucide/vue'
import { computed } from 'vue'

import { Button } from '@/shared/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/shared/components/ui/dropdown-menu'
import UiBadge from '@/shared/components/ui/UiBadge.vue'
import type { LlmProvider } from '@/shared/types/quant'

/**
 * 供应商卡（Vercel Integrations 一路）：
 * 左上一枚品牌方块（按协议着色的首字母），名称 + 协议，右上 `⋯` 菜单；
 * 中段等宽的端点行与模型 chips；底部健康点 + 「n / m 启用」读数 + 主操作。
 * 整卡可点进编辑；默认线路带主色描边。
 */
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

const isAnthropic = computed(() => props.provider.protocol === 'anthropic')
const protocolLabel = computed(() => (isAnthropic.value ? 'Anthropic' : 'OpenAI 兼容'))

const host = computed(() => {
  try {
    return new URL(props.provider.base_url).host
  } catch {
    return props.provider.base_url.replace(/^https?:\/\//, '').split('/')[0] || props.provider.base_url
  }
})

const keyLabel = computed(() =>
  props.provider.key_last4 ? `···${props.provider.key_last4}` : '未设密钥',
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

/** 健康点：有密钥且验证过 = ok；有密钥未验证 = info；无密钥 = warn */
const health = computed((): { tone: 'ok' | 'info' | 'warn'; label: string } => {
  if (!props.provider.has_key) return { tone: 'warn', label: '缺密钥' }
  if (props.provider.validated_at) return { tone: 'ok', label: `已验证 ${props.provider.validated_at.slice(0, 10)}` }
  return { tone: 'info', label: '未验证' }
})
</script>

<template>
  <article
    class="prov-card"
    :class="{ 'is-default': provider.is_default, 'is-anthropic': isAnthropic }"
    role="button"
    tabindex="0"
    :aria-label="`编辑 ${provider.name}`"
    @click="emit('edit')"
    @keydown.enter.self.prevent="emit('edit')"
    @keydown.space.self.prevent="emit('edit')"
  >
    <header class="prov-card__head">
      <span class="prov-card__mark" aria-hidden="true">{{ initial }}</span>
      <div class="prov-card__identity">
        <div class="prov-card__title-row">
          <strong class="prov-card__name">{{ provider.name }}</strong>
          <UiBadge v-if="provider.is_default" variant="default">默认</UiBadge>
        </div>
        <p class="prov-card__meta">{{ protocolLabel }}<template v-if="provider.note"> · {{ provider.note }}</template></p>
      </div>
      <DropdownMenu>
        <DropdownMenuTrigger as-child>
          <Button variant="ghost" size="icon-sm" :disabled="busy" aria-label="更多操作" @click.stop>
            <Ellipsis />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" @click.stop>
          <DropdownMenuItem @select="emit('catalog')">模型目录</DropdownMenuItem>
          <DropdownMenuItem @select="emit('pull')">拉取模型</DropdownMenuItem>
          <DropdownMenuItem @select="emit('test')">测试连接</DropdownMenuItem>
          <DropdownMenuItem v-if="!provider.is_default" @select="emit('set-default')">设为默认</DropdownMenuItem>
          <DropdownMenuSeparator />
          <DropdownMenuItem variant="destructive" @select="emit('remove')">删除</DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </header>

    <div class="prov-card__endpoint" :title="provider.base_url">
      <span class="prov-card__host">{{ host }}</span>
      <span class="prov-card__key" :class="{ 'is-ok': provider.has_key }">
        <KeyRound aria-hidden="true" />
        {{ keyLabel }}
      </span>
    </div>

    <div v-if="chips.length" class="prov-card__chips">
      <span
        v-for="(id, i) in chips"
        :key="id"
        class="model-chip"
        :class="{ 'is-active': id === provider.default_model || (!provider.default_model && i === 0) }"
      >
        {{ id }}
      </span>
      <span v-if="extraCount > 0" class="model-chip model-chip--more">+{{ extraCount }}</span>
    </div>
    <p v-else class="prov-card__empty">尚未拉取模型，先在菜单里「拉取模型」</p>

    <footer class="prov-card__foot" @click.stop>
      <span class="prov-card__health" :class="`is-${health.tone}`" :title="health.label">
        <span class="prov-card__dot" aria-hidden="true" />
        <span class="prov-card__count">{{ enabledCount }}<small>/{{ catalogTotal }} 模型启用</small></span>
      </span>
      <div class="prov-card__actions">
        <Button v-if="!provider.is_default" variant="ghost" size="sm" :disabled="busy" @click="emit('set-default')">
          设为默认
        </Button>
        <Button variant="outline" size="sm" :disabled="busy" @click="emit('edit')">编辑</Button>
      </div>
    </footer>
  </article>
</template>

<style scoped>
.prov-card {
  --prov-tint: var(--seal);
  position: relative;
  display: flex;
  flex-direction: column;
  gap: var(--gap-3);
  min-width: 0;
  padding: var(--gap-4);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-lg);
  background: var(--surface);
  box-shadow: var(--shadow-xs);
  cursor: pointer;
  transition:
    border-color var(--dur-fast) var(--ease),
    box-shadow var(--dur-fast) var(--ease),
    transform var(--dur-fast) var(--ease);
}

.prov-card.is-anthropic {
  --prov-tint: var(--peach);
}

.prov-card:hover {
  border-color: var(--border-default);
  box-shadow: var(--shadow-sm);
}

.prov-card:active {
  transform: translateY(1px);
}

.prov-card:focus-visible {
  outline: 2px solid var(--focus-ring);
  outline-offset: 2px;
}

.prov-card.is-default {
  border-color: var(--seal-border);
  box-shadow:
    0 0 0 1px var(--seal-border),
    var(--shadow-xs);
}

.prov-card__head {
  display: flex;
  align-items: flex-start;
  gap: var(--gap-3);
}

.prov-card__mark {
  display: grid;
  flex: 0 0 auto;
  place-items: center;
  width: 40px;
  height: 40px;
  border-radius: var(--radius);
  background:
    linear-gradient(145deg, color-mix(in oklab, var(--prov-tint) 22%, transparent), color-mix(in oklab, var(--prov-tint) 8%, transparent)),
    var(--surface-raised);
  border: 1px solid color-mix(in oklab, var(--prov-tint) 30%, transparent);
  color: color-mix(in oklab, var(--prov-tint) 85%, var(--text-primary));
  font-family: var(--mono);
  font-size: var(--fs-title);
  font-weight: 700;
}

.prov-card__identity {
  flex: 1 1 auto;
  min-width: 0;
}

.prov-card__title-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--gap-2);
}

.prov-card__name {
  color: var(--text-primary);
  font-size: var(--fs-title);
  font-weight: 600;
  letter-spacing: -0.01em;
  overflow-wrap: anywhere;
}

.prov-card__meta {
  margin: 2px 0 0;
  overflow: hidden;
  color: var(--text-tertiary);
  font-size: var(--fs-aux);
  white-space: nowrap;
  text-overflow: ellipsis;
}

.prov-card__endpoint {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--gap-3);
  min-width: 0;
  padding: 6px var(--gap-3);
  border-radius: var(--radius);
  background: var(--surface-sunken);
  font-family: var(--mono);
  font-size: var(--fs-aux);
  font-variant-numeric: tabular-nums;
}

.prov-card__host {
  min-width: 0;
  overflow: hidden;
  color: var(--text-secondary);
  white-space: nowrap;
  text-overflow: ellipsis;
}

.prov-card__key {
  display: inline-flex;
  flex: 0 0 auto;
  align-items: center;
  gap: 4px;
  color: var(--warn-ink);
}

.prov-card__key.is-ok {
  color: var(--text-tertiary);
}

.prov-card__key :deep(svg) {
  width: 12px;
  height: 12px;
}

.prov-card__chips {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--gap-1);
}

.model-chip {
  max-width: 100%;
  overflow: hidden;
  padding: 2px 8px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-pill);
  background: var(--surface);
  color: var(--text-secondary);
  font-family: var(--mono);
  font-size: var(--fs-kicker);
  white-space: nowrap;
  text-overflow: ellipsis;
}

.model-chip.is-active {
  border-color: var(--seal-border);
  background: var(--seal-soft);
  color: var(--seal-ink);
  font-weight: 600;
}

.model-chip--more {
  border-style: dashed;
  color: var(--text-tertiary);
}

.prov-card__empty {
  margin: 0;
  color: var(--text-tertiary);
  font-size: var(--fs-aux);
}

.prov-card__foot {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: var(--gap-2);
  margin-top: auto;
  padding-top: var(--gap-3);
  border-top: 1px solid var(--border-subtle);
}

.prov-card__health {
  display: inline-flex;
  align-items: center;
  gap: var(--gap-2);
  min-width: 0;
}

.prov-card__dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--border-strong);
  box-shadow: 0 0 0 3px color-mix(in oklab, var(--border-strong) 25%, transparent);
}

.prov-card__health.is-ok .prov-card__dot {
  background: var(--ok);
  box-shadow: 0 0 0 3px var(--ok-soft);
}

.prov-card__health.is-warn .prov-card__dot {
  background: var(--warn);
  box-shadow: 0 0 0 3px var(--warn-soft);
}

.prov-card__health.is-info .prov-card__dot {
  background: var(--info);
  box-shadow: 0 0 0 3px var(--info-soft);
}

.prov-card__count {
  color: var(--text-primary);
  font-family: var(--mono);
  font-size: var(--fs-ui);
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}

.prov-card__count small {
  color: var(--text-tertiary);
  font-family: var(--font);
  font-size: var(--fs-kicker);
  font-weight: 500;
}

.prov-card__actions {
  display: flex;
  align-items: center;
  gap: var(--gap-1);
}

@media (prefers-reduced-motion: reduce) {
  .prov-card {
    transition: none;
  }
}
</style>
