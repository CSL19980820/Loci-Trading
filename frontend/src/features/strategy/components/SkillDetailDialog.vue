<script setup lang="ts">
import { vBusy } from '@/shared/directives/busy'
import { default as DialogPanel } from '@/shared/components/ui/app/DialogPanel.vue'
import { default as TabSet } from '@/shared/components/ui/app/TabSet.vue'
import { default as TabPage } from '@/shared/components/ui/app/TabPage.vue'
import { StatusBadge } from '@/shared/components/ui/app/presentation'
import { default as DataGrid } from '@/shared/components/ui/app/DataGrid.vue'
import { default as DataColumn } from '@/shared/components/ui/app/DataColumn.vue'
import { default as ActionButton } from '@/shared/components/ui/app/ActionButton.vue'

import { computed, onScopeDispose, ref, watch } from 'vue'

import { getSkill } from '@/shared/api/quant'
import type { Skill, SkillJob } from '@/shared/types/quant'
import EmptyState from '@/shared/components/ui/EmptyState.vue'

import ManualInline from './ManualInline.vue'
import SkillJobConfigPanel from './SkillJobConfigPanel.vue'
import SkillStrategyConfigPanel from './SkillStrategyConfigPanel.vue'
import { parseSkillManual } from '../composables/skillManual'

const props = defineProps<{
  modelValue: boolean
  skill: Skill | null
}>()

const emit = defineEmits<{
  'update:modelValue': [boolean]
  openScreen: [slug: string]
  remove: [skill: Skill]
  saved: [job: SkillJob]
}>()

const jobPanel = ref<InstanceType<typeof SkillJobConfigPanel> | null>(null)
const strategyPanel = ref<InstanceType<typeof SkillStrategyConfigPanel> | null>(null)

type ToolSpec = {
  name: string
  description: string
  kind: string
  params: string[]
}

const ISOLATION_LABEL: Record<string, string> = {
  normal: '常规',
  skill_only: '仅技能上下文',
}

const POLICY_LABEL: Record<string, string> = {
  research: '研究',
  trading_voice: '交易口径',
}

const TOOL_KIND_LABEL: Record<string, string> = {
  cli: '本机命令',
  mcp: 'MCP',
  builtin: '内置',
}

const open = computed({
  get: () => props.modelValue,
  set: (v: boolean) => emit('update:modelValue', v),
})

const dialogSize = computed(() => {
  if (typeof window !== 'undefined' && window.innerWidth <= 720) return '94vw'
  return '52rem'
})

const tab = ref('basics')
const loadingBody = ref(false)
const body = ref('')
const bodyError = ref('')
let bodyLoadToken = 0

onScopeDispose(() => {
  bodyLoadToken += 1
})

const title = computed(() => props.skill?.name || '技能')

const statusLabel = computed(() => (props.skill?.enabled === false ? '停用' : '启用'))

const metaRows = computed(() => {
  const skill = props.skill
  if (!skill) return [] as { label: string; value: string }[]
  const rows = [
    { label: '版本', value: skill.version || '—' },
    { label: '状态', value: statusLabel.value },
    { label: '上下文', value: ISOLATION_LABEL[skill.isolation || 'normal'] || '常规' },
    { label: '口径', value: POLICY_LABEL[skill.policy || 'research'] || '研究' },
  ]
  return rows
})

/** frontmatter 的 tools 若是新式 dict 写法会带说明；旧式只有名字。 */
const toolSpecs = computed<ToolSpec[]>(() => {
  const specs = props.skill?.tool_specs
  if (!Array.isArray(specs)) return []
  return specs.map((raw) => {
    const schema = raw.args_schema
    const properties =
      schema && typeof schema === 'object' && 'properties' in schema
        ? (schema as { properties?: Record<string, unknown> }).properties
        : undefined
    return {
      name: String(raw.name ?? ''),
      description: String(raw.description ?? ''),
      kind: String(raw.kind ?? 'cli'),
      params: properties ? Object.keys(properties) : [],
    }
  })
})

/** 声明了 tools 却没写说明的旧包，只列名字。 */
const bareTools = computed(() => {
  if (toolSpecs.value.length) return []
  const tools = props.skill?.allowed_tools
  return Array.isArray(tools) ? tools.map((item) => String(item)) : []
})

const hasTools = computed(() => toolSpecs.value.length > 0 || bareTools.value.length > 0)

const mcpServers = computed(() => props.skill?.mcp_servers ?? [])

/** 专属战法 = 声明了 strategy_skill / signal_engine / signals 之一 */
const isStrategySkill = computed(() => {
  const meta = props.skill?.metadata as Record<string, unknown> | undefined
  if (!meta) return false
  return Boolean(meta.strategy_skill || meta.signal_engine || meta.signals)
})

const manualBlocks = computed(() => (body.value ? parseSkillManual(body.value) : []))

function toolKindLabel(kind: string): string {
  return TOOL_KIND_LABEL[kind] || kind
}


function tableBody(rows: string[][]): Record<string, string>[] {
  return rows.slice(1).map((cells) => Object.fromEntries(cells.map((c, i) => [`c${i}`, c])))
}

watch(
  () => [props.modelValue, props.skill?.slug] as const,
  async ([opened, slug]) => {
    const token = ++bodyLoadToken
    if (!opened || !slug) {
      loadingBody.value = false
      return
    }
    tab.value = 'config'
    body.value = ''
    bodyError.value = ''
    loadingBody.value = true
    try {
      const full = await getSkill(slug)
      if (token !== bodyLoadToken) return
      body.value = (full.instructions || '').trim()
    } catch {
      if (token !== bodyLoadToken) return
      bodyError.value = '读不到技能说明书正文，确认技能目录仍在本机'
    } finally {
      if (token === bodyLoadToken) loadingBody.value = false
    }
  },
  { immediate: true },
)

async function saveJob(): Promise<void> {
  if (isStrategySkill.value) {
    await strategyPanel.value?.save()
  } else {
    await jobPanel.value?.save()
  }
}
</script>

<template>
  <DialogPanel
    v-model="open"
    :title="title"
    :width="dialogSize"
    destroy-on-close
    class="skill-detail-dialog"
  >
    <template v-if="skill">
      <TabSet v-model="tab" class="detail-tabs">
        <TabPage label="配置" name="config">
          <SkillStrategyConfigPanel
            v-if="skill && isStrategySkill"
            ref="strategyPanel"
            :slug="skill.slug"
            @saved="(cfg) => skill && emit('saved', { slug: skill.slug, bound: true, config: cfg } as SkillJob)"
          />
          <SkillJobConfigPanel
            v-else-if="skill"
            ref="jobPanel"
            :slug="skill.slug"
            @saved="(job) => emit('saved', job)"
          />
        </TabPage>

        <TabPage label="基础信息" name="basics">
          <div class="meta-grid">
            <div v-for="row in metaRows" :key="row.label" class="meta-cell">
              <span class="dim">{{ row.label }}</span>
              <strong>{{ row.value }}</strong>
            </div>
          </div>
          <div class="meta-desc">
            <span class="dim">简述</span>
            <strong>{{ skill.description || '—' }}</strong>
          </div>
          <div v-if="mcpServers.length" class="meta-desc">
            <span class="dim">MCP 服务</span>
            <div class="chip-row">
              <StatusBadge v-for="name in mcpServers" :key="name" size="small" effect="plain">
                {{ name }}
              </StatusBadge>
            </div>
          </div>
        </TabPage>

        <TabPage label="说明书" name="manual">
          <div v-busy="loadingBody" class="manual">
            <article v-if="manualBlocks.length" class="manual-body">
              <template v-for="(block, index) in manualBlocks" :key="index">
                <p v-if="block.type === 'heading'" class="md-heading" :data-level="block.level">
                  <ManualInline :text="block.text" />
                </p>
                <pre v-else-if="block.type === 'code'" class="md-code">{{ block.text }}</pre>
                <ol v-else-if="block.type === 'list' && block.ordered" class="md-list">
                  <li v-for="(item, i) in block.items" :key="i">
                    <ManualInline :text="item" />
                  </li>
                </ol>
                <ul v-else-if="block.type === 'list'" class="md-list">
                  <li v-for="(item, i) in block.items" :key="i">
                    <ManualInline :text="item" />
                  </li>
                </ul>
                <p v-else-if="block.type === 'quote'" class="md-quote">
                  <ManualInline :text="block.text" />
                </p>
                <DataGrid
                  v-else-if="block.type === 'table'"
                  :data="tableBody(block.rows)"
                  size="small"
                  border
                  class="md-table"
                >
                  <DataColumn
                    v-for="(head, col) in block.rows[0]"
                    :key="col"
                    :label="head"
                    :prop="`c${col}`"
                    min-width="96"
                  >
                    <template #default="{ row }">
                      <ManualInline :text="String(row[`c${col}`] ?? '')" />
                    </template>
                  </DataColumn>
                </DataGrid>
                <p v-else class="md-para">
                  <ManualInline :text="block.text" />
                </p>
              </template>
            </article>
            <EmptyState
              v-else-if="!loadingBody"
              :description="bodyError ? '读不到说明书正文' : '说明书只有元数据'"
              :reason="bodyError ? '确认技能目录仍在本机' : '没有正文可展示'"
            />
          </div>
        </TabPage>

        <TabPage v-if="hasTools" label="工具" name="tools">
          <ul v-if="toolSpecs.length" class="tool-list">
            <li v-for="tool in toolSpecs" :key="tool.name" class="tool-item">
              <div class="tool-head">
                <strong class="mono">{{ tool.name }}</strong>
                <StatusBadge size="small" effect="plain">{{ toolKindLabel(tool.kind) }}</StatusBadge>
              </div>
              <p class="tool-desc">{{ tool.description || '未写说明' }}</p>
              <div v-if="tool.params.length" class="chip-row">
                <span class="dim">入参</span>
                <StatusBadge v-for="key in tool.params" :key="key" size="small" effect="plain">
                  {{ key }}
                </StatusBadge>
              </div>
            </li>
          </ul>
          <template v-else>
            <p class="dim">该技能只声明了工具名，没有写逐项说明。</p>
            <div class="chip-row">
              <StatusBadge v-for="name in bareTools" :key="name" size="small" effect="plain">
                {{ name }}
              </StatusBadge>
            </div>
          </template>
        </TabPage>
      </TabSet>
    </template>

    <template #footer>
      <ActionButton
        v-if="skill"
        tone="danger"
        plain
        @click="emit('remove', skill); open = false"
      >
        卸载
      </ActionButton>
      <ActionButton
        v-if="tab === 'config'"
        tone="primary"
        :busy="Boolean(isStrategySkill ? strategyPanel?.saving : jobPanel?.saving)"
        :disabled="!skill"
        @click="saveJob"
      >
        保存配置
      </ActionButton>
      <ActionButton access="read"
        v-else
        tone="primary"
        :disabled="!skill || skill.enabled === false"
        @click="skill && emit('openScreen', skill.slug); open = false"
      >
        去选股
      </ActionButton>
    </template>
  </DialogPanel>
</template>

<style scoped>
.detail-tabs :deep(.tab-set__list) {
  margin-bottom: 0.75rem;
}
.meta-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0.35rem 0.75rem;
}
.meta-cell,
.meta-desc {
  display: flex;
  flex-direction: column;
  gap: 0.2rem;
  padding: 0.45rem 0;
  border-bottom: 1px solid var(--rule);
}
.meta-desc {
  margin-top: 0.25rem;
}
.dim {
  color: var(--mist);
  font-size: 0.76rem;
}
.mono {
  font-family: var(--mono);
  font-size: var(--fs-aux);
}
.chip-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.3rem;
}

.manual {
  max-height: 62vh;
  overflow: auto;
}
.manual-body {
  padding: 1rem 1.15rem;
  border: 1px solid var(--rule);
  border-radius: var(--radius);
  background: var(--surface);
  font-size: var(--fs-body);
  line-height: 1.7;
  word-break: break-word;
}
.md-heading {
  margin: 1.1rem 0 0.4rem;
  font-weight: 650;
  line-height: 1.35;
}
.md-heading:first-child {
  margin-top: 0;
}
.md-heading[data-level='1'] {
  font-size: 1.15rem;
}
.md-heading[data-level='2'] {
  font-size: 1.02rem;
}
.md-heading[data-level='3'],
.md-heading[data-level='4'],
.md-heading[data-level='5'],
.md-heading[data-level='6'] {
  font-size: 0.92rem;
  color: var(--muted);
}
.md-para {
  margin: 0 0 0.65rem;
}
.md-list {
  margin: 0 0 0.7rem;
  padding-left: 1.25rem;
}
.md-list li {
  margin-bottom: 0.28rem;
}
.md-quote {
  margin: 0 0 0.7rem;
  padding: 0.5rem 0.7rem;
  border-radius: var(--radius);
  background: var(--surface-sunken);
  color: var(--muted);
}
.md-code {
  margin: 0 0 0.7rem;
  padding: 0.55rem 0.7rem;
  border-radius: var(--radius);
  background: var(--surface-sunken);
  font-family: var(--mono);
  font-size: var(--fs-aux);
  line-height: 1.55;
  white-space: pre-wrap;
}
.md-table {
  margin-bottom: 0.85rem;
  width: 100%;
}

.tool-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  max-height: 62vh;
  overflow: auto;
}
.tool-item {
  padding: 0.55rem 0.65rem;
  border: 1px solid var(--rule);
  border-radius: var(--radius);
}
.tool-head {
  display: flex;
  align-items: center;
  gap: 0.4rem;
}
.tool-desc {
  margin: 0.25rem 0 0.35rem;
  font-size: var(--fs-aux);
  line-height: 1.5;
  color: var(--muted);
}
</style>
