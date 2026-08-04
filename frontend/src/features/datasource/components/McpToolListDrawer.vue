<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'

import { getMcpServers } from '@/shared/api/quant'
import { toErrorMessage } from '@/shared/lib/errors'
import type { McpServer } from '@/shared/types/quant'

const BUILTIN_NAME = 'loci-market'

const open = defineModel<boolean>({ required: true })

const server = ref<McpServer | null>(null)
const pendingLoads = ref(0)
const loading = computed(() => pendingLoads.value > 0)
const error = ref('')
let active = true
let loadVersion = 0

const tools = computed(() => server.value?.tools ?? [])
const laneTools = computed(() =>
  tools.value.filter((item) => item.name !== 'akshare_call' && !item.name.startsWith('ak_')),
)
const akshareTools = computed(() =>
  tools.value.filter((item) => item.name === 'akshare_call' || item.name.startsWith('ak_')),
)

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
  <el-drawer v-model="open" size="min(520px, 94vw)" direction="rtl">
    <template #header="{ titleId, titleClass }">
      <div class="mcp-head">
        <h4 :id="titleId" :class="titleClass">MCP 工具清单</h4>
        <code>{{ BUILTIN_NAME }}</code>
      </div>
    </template>

    <p class="mcp-note">
      AI 技能声明 <code>mcp_servers: [loci-market]</code> 后拿到的就是这份清单：
      线路工具跟着数据源启停走；AkShare 通过单一工具 <code>akshare_call</code> 按名调用目录内任意
      <code>stock_*</code>（不再逐接口上桌）。
    </p>

    <el-alert v-if="error" :title="error" type="warning" show-icon :closable="false" class="mcp-alert" />

    <el-skeleton v-if="loading && !tools.length" :rows="4" animated />
    <template v-else>
      <section class="mcp-group">
        <h5>线路工具 <b>{{ laneTools.length }}</b></h5>
        <el-empty v-if="!laneTools.length" description="所有取数线路都被停用了" :image-size="56" />
        <ul v-else class="mcp-list">
          <li v-for="item in laneTools" :key="item.name">
            <code>{{ item.name }}</code>
            <span>{{ item.description }}</span>
          </li>
        </ul>
      </section>

      <section class="mcp-group">
        <h5>AkShare 接口 <b>{{ akshareTools.length }}</b></h5>
        <el-empty
          v-if="!akshareTools.length"
          description="未挂载 akshare_call（检查内置 MCP）"
          :image-size="56"
        />
        <ul v-else class="mcp-list">
          <li v-for="item in akshareTools" :key="item.name">
            <code>{{ item.name }}</code>
            <span>{{ item.description }}</span>
          </li>
        </ul>
      </section>
    </template>

    <template #footer>
      <el-button :loading="loading" @click="load()">重新读取</el-button>
      <el-button type="primary" @click="open = false">关闭</el-button>
    </template>
  </el-drawer>
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
}

.mcp-note {
  margin: 0 0 0.7rem;
  font-size: 0.8rem;
  line-height: 1.5;
  color: var(--muted);
}

.mcp-note code {
  font: 0.76rem var(--mono);
}

.mcp-alert {
  margin-bottom: 0.6rem;
}

.mcp-group {
  margin-bottom: 0.9rem;
}

.mcp-group h5 {
  margin: 0 0 0.4rem;
  font-family: var(--font-display);
  font-size: 0.92rem;
}

.mcp-group h5 b {
  margin-left: 0.25rem;
  font: 650 0.9rem var(--mono);
  color: var(--ink);
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
  gap: 0.15rem;
  padding: 0.4rem 0.55rem;
  border: 1px solid var(--rule);
  border-radius: 4px;
  background: var(--paper);
}

.mcp-list code {
  font: 650 0.8rem var(--mono);
  color: var(--ink);
}

.mcp-list span {
  font-size: 0.78rem;
  line-height: 1.45;
  color: var(--muted);
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 3;
  overflow: hidden;
}
</style>
