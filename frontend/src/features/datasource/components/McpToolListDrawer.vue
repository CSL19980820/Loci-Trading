<script setup lang="ts">
import { default as SidePanel } from '@/shared/components/ui/app/SidePanel.vue'
import { default as HintTooltip } from '@/shared/components/ui/app/HintTooltip.vue'
import { Notice, SkeletonBlock } from '@/shared/components/ui/app/presentation'
import { default as TextField } from '@/shared/components/ui/app/TextField.vue'
import { default as ActionButton } from '@/shared/components/ui/app/ActionButton.vue'

import { computed, onUnmounted, ref, watch } from 'vue'

import { getMcpServers } from '@/shared/api/quant'
import { toErrorMessage } from '@/shared/lib/errors'
import type { McpServer } from '@/shared/types/quant'
import EmptyState from '@/shared/components/ui/EmptyState.vue'

const BUILTIN_NAME = 'loci-market'

const open = defineModel<boolean>({ required: true })

const server = ref<McpServer | null>(null)
const pendingLoads = ref(0)
const loading = computed(() => pendingLoads.value > 0)
const error = ref('')
let active = true
let loadVersion = 0

const laneQuery = ref('')
const akQuery = ref('')

const tools = computed(() => server.value?.tools ?? [])
const laneTools = computed(() =>
  tools.value.filter((item) => item.name !== 'akshare_call' && !item.name.startsWith('ak_')),
)
const akshareTools = computed(() =>
  tools.value.filter((item) => item.name === 'akshare_call' || item.name.startsWith('ak_')),
)

function match(list: McpServer['tools'], keyword: string): McpServer['tools'] {
  const key = keyword.trim().toLowerCase()
  if (!key) return list
  return list.filter((item) => `${item.name} ${item.description ?? ''}`.toLowerCase().includes(key))
}

const laneShown = computed(() => match(laneTools.value, laneQuery.value))
const akshareShown = computed(() => match(akshareTools.value, akQuery.value))

/** 清单口径原来是抽屉顶上一整段常驻说明，压进标题旁的 tooltip。 */
const scopeTip =
  'AI 技能声明 mcp_servers: [loci-market] 后拿到的就是这份清单：' +
  '线路工具跟着数据源启停走；AkShare 只挂 akshare_call 一个工具，按名调用目录内任意 stock_*。'

async function load(): Promise<void> {
  const version = ++loadVersion
  pendingLoads.value += 1
  try {
    const rows = await getMcpServers()
    if (!active || version !== loadVersion) return
    server.value = rows.find((row) => row.name === BUILTIN_NAME) ?? null
    error.value = server.value ? '' : '内置 MCP 没有出现在服务器列表里'
  } catch (caught: unknown) {
    if (!active || version !== loadVersion) return
    error.value = toErrorMessage(caught, '读取 MCP 工具清单失败')
  } finally {
    if (active) pendingLoads.value = Math.max(0, pendingLoads.value - 1)
  }
}

// 每次打开都重新拉：刚改过启停，清单就该是新的
watch(open, (visible) => {
  if (visible) {
    void load()
  } else {
    loadVersion += 1
  }
})

onUnmounted(() => {
  active = false
  loadVersion += 1
})
</script>

<template>
  <SidePanel v-model="open" class="source-mcp-drawer" size="min(520px, 100vw)" direction="rtl" append-to-body>
    <template #header="{ titleId, titleClass }">
      <div class="mcp-head">
        <h4 :id="titleId" :class="titleClass">MCP 工具清单</h4>
        <HintTooltip :content="scopeTip" placement="bottom-start">
          <code>{{ BUILTIN_NAME }}</code>
        </HintTooltip>
      </div>
    </template>

    <Notice v-if="error" :title="error" tone="warning" show-icon :closable="false" class="mcp-alert" />

    <SkeletonBlock v-if="loading && !tools.length" :rows="4" animated />
    <template v-else>
      <!-- 两块并列清单要区分，标题保留；但压成一行：标题 + 计数 + 本块筛选控件同行 -->
      <section class="mcp-group">
        <header class="mcp-group__head">
          <h5 class="mcp-group__title">
            线路工具 <b>{{ laneShown.length }}</b>
            <span v-if="laneShown.length !== laneTools.length" class="mcp-group__total">
              / {{ laneTools.length }}
            </span>
          </h5>
          <TextField
            v-model="laneQuery"
            class="mcp-group__filter"
            size="small"
            clearable
            placeholder="筛线路工具"
            aria-label="筛选线路工具"
          />
        </header>
        <EmptyState
          v-if="!laneShown.length"
          :description="laneTools.length ? '没有匹配的工具' : '所有取数线路都被停用了'"
          reason="调整筛选或启用线路"
        />
        <ul v-else class="mcp-list">
          <li v-for="item in laneShown" :key="item.name">
            <code>{{ item.name }}</code>
            <span>{{ item.description }}</span>
          </li>
        </ul>
      </section>

      <section class="mcp-group">
        <header class="mcp-group__head">
          <h5 class="mcp-group__title">
            AkShare 接口 <b>{{ akshareShown.length }}</b>
            <span v-if="akshareShown.length !== akshareTools.length" class="mcp-group__total">
              / {{ akshareTools.length }}
            </span>
          </h5>
          <TextField
            v-model="akQuery"
            class="mcp-group__filter"
            size="small"
            clearable
            placeholder="筛 AkShare 工具"
            aria-label="筛选 AkShare 工具"
          />
        </header>
        <EmptyState
          v-if="!akshareShown.length"
          :description="akshareTools.length ? '没有匹配的工具' : '未挂载 akshare_call'"
          reason="检查内置 MCP 是否挂载"
        />
        <ul v-else class="mcp-list">
          <li v-for="item in akshareShown" :key="item.name">
            <code>{{ item.name }}</code>
            <span>{{ item.description }}</span>
          </li>
        </ul>
      </section>
    </template>

    <template #footer>
      <ActionButton access="read" :busy="loading" @click="load()">重新读取</ActionButton>
      <ActionButton access="read" tone="primary" @click="open = false">关闭</ActionButton>
    </template>
  </SidePanel>
</template>

<style scoped>
.mcp-head {
  display: flex;
  align-items: baseline;
  gap: 0.5rem;
  min-width: 0;
  padding-right: 1.6rem;
}

.mcp-head code {
  font: 0.76rem var(--mono);
  color: var(--mist);
  cursor: help;
}

.mcp-alert {
  margin-bottom: 0.6rem;
}

.mcp-group {
  margin-bottom: var(--gap-3);
}

/* 标题不独占一行：计数与本块筛选框都挂在同一条功能行上 */
.mcp-group__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--gap-2);
  flex-wrap: wrap;
  margin-bottom: var(--gap-2);
  padding: var(--gap-2);
  border: 1px solid var(--rule);
  border-radius: var(--radius);
  background: var(--surface-sunken);
  min-width: 0;
}

.mcp-group__title {
  margin: 0;
  font-family: var(--font);
  font-size: var(--fs-body);
  white-space: nowrap;
}

.mcp-group__title b {
  margin-left: 0.25rem;
  font: 650 0.9rem var(--mono);
  color: var(--ink);
}

.mcp-group__total {
  font: 0.78rem var(--mono);
  color: var(--mist);
}

.mcp-group__filter {
  max-width: 13rem;
}

.mcp-list {
  display: grid;
  gap: 0.4rem;
  margin: 0;
  padding: 0;
  list-style: none;
}

.mcp-list li {
  display: grid;
  gap: var(--gap-1);
  padding: var(--gap-2) var(--gap-3);
  border: 1px solid var(--rule);
  border-radius: var(--radius);
  background: var(--surface);
}

.mcp-list code {
  font: 600 var(--fs-aux) var(--mono);
  overflow-wrap: anywhere;
  color: var(--ink);
}

.mcp-list span {
  font-size: var(--fs-aux);
  line-height: 1.45;
  color: var(--muted);
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 3;
  overflow: hidden;
}
</style>
<style scoped>
.mcp-head { flex-wrap: wrap; gap: var(--gap-2); }
.source-mcp-drawer :deep(.side-panel__header) { border-bottom: 1px solid var(--rule); padding-bottom: var(--gap-3); }
.source-mcp-drawer :deep(.side-panel__footer) { border-top: 1px solid var(--rule); background: var(--surface-sunken); }
</style>
