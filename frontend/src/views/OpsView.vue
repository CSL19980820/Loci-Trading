<template>
  <header class="toolbar">
    <div class="toolbar-title">
      <h1>运维</h1>
      <span v-if="schedule" class="muted mono">
        调度{{ schedule.running ? `运行中 · ${schedule.jobs.length} 个任务` : '未启用' }}
      </span>
    </div>
    <button class="quiet-button" type="button" :disabled="busy" @click="reload">刷新</button>
  </header>

  <p v-if="notice" class="toast" role="status">{{ notice }}</p>
  <p v-if="errorText" class="error-banner" role="alert"><span>{{ errorText }}</span></p>

  <!-- 技能包 -->
  <section class="panel mb">
    <div class="panel-bar">
      <h2>技能包 <span class="chip">{{ skills.length }}</span></h2>
      <label class="text-link upload-label">
        安装 zip
        <input type="file" accept=".zip" hidden @change="onUpload" />
      </label>
    </div>
    <ul v-if="skills.length" class="rows">
      <li v-for="skill in skills" :key="skill.slug">
        <div class="row-main">
          <strong>{{ skill.name }}</strong>
          <span class="code">{{ skill.slug }}</span>
          <span v-if="skill.version" class="tag">v{{ skill.version }}</span>
          <span v-if="!skill.enabled" class="chip muted-chip">已停用</span>
        </div>
        <p class="reason">{{ skill.description }}</p>
        <div class="row-meta">
          <span v-if="skill.default_cron" class="mono">建议调度 {{ skill.default_cron }}</span>
          <span v-if="skill.allowed_tools.length" class="dim">
            工具 {{ skill.allowed_tools.join(', ') }}
          </span>
          <button class="quiet-button" type="button" :disabled="busy" @click="dropSkill(skill.slug)">
            卸载
          </button>
        </div>
      </li>
    </ul>
    <p v-else class="empty pad">尚未安装技能包。上传一个 zip，它就成为一个可定时运行的模式。</p>
    <p class="form-hint">
      包内必须有 SKILL.md：YAML frontmatter 给元数据，正文是给模型的指令。
      上传时会做 Zip Slip、符号链接、zip 炸弹与可执行文件检查，任何一条不过即整包拒绝。
    </p>
  </section>

  <!-- MCP server -->
  <section class="panel mb">
    <div class="panel-bar">
      <h2>MCP Server <span class="chip">{{ mcpServers.length }}</span></h2>
      <button class="text-link" type="button" @click="mcpFormOpen = !mcpFormOpen">
        {{ mcpFormOpen ? '收起' : '添加' }}
      </button>
    </div>

    <form v-if="mcpFormOpen" class="trade-form inline-form" @submit.prevent="submitMcp">
      <fieldset>
        <label>
          名称
          <input v-model.trim="mcpForm.name" required placeholder="my-data-source" />
        </label>
        <label>
          URL
          <input v-model.trim="mcpForm.url" required placeholder="https://mcp.example.com" />
        </label>
        <label>
          Token（可选）
          <input v-model.trim="mcpForm.token" type="password" autocomplete="off" placeholder="Bearer token，公开 server 留空" />
        </label>
        <label>
          专用代理
          <input v-model.trim="mcpForm.proxy_url" placeholder="http://172.17.0.1:7890" />
        </label>
        <label>
          备注
          <input v-model.trim="mcpForm.note" placeholder="用途说明" />
        </label>
        <label class="checkbox-label">
          <input v-model="mcpForm.verify" type="checkbox" />
          保存时握手校验（推荐）
        </label>
      </fieldset>
      <div class="dialog-actions">
        <button class="quiet-button" type="button" @click="mcpFormOpen = false">取消</button>
        <button class="primary-button" type="submit" :disabled="busy">保存并发现工具</button>
      </div>
      <p class="form-hint">
        保存时发起 tools/list 发现工具列表；校验失败不入库。Token 用 AES-256-GCM 加密存储，只回末四位。
      </p>
    </form>

    <div v-if="mcpServers.length" class="table-wrap">
      <table class="dense">
        <thead>
          <tr>
            <th>名称</th>
            <th>URL</th>
            <th>Token</th>
            <th class="r">工具数</th>
            <th>同步时间</th>
            <th class="r">状态</th>
            <th class="r">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in mcpServers" :key="item.id">
            <td><strong>{{ item.name }}</strong></td>
            <td class="mono dim">{{ item.url }}</td>
            <td class="mono">{{ item.token_last4 || '无' }}</td>
            <td class="r mono">{{ item.tools.length }}</td>
            <td class="mono dim">{{ item.tools_synced_at?.slice(0, 16) || '—' }}</td>
            <td class="r">
              <span :class="item.is_active ? 'tag' : 'chip muted-chip'">{{ item.is_active ? '启用' : '停用' }}</span>
            </td>
            <td class="r">
              <button class="quiet-button" type="button" :disabled="busy" @click="refreshMcp(item.name)">刷新</button>
              <button class="quiet-button" type="button" :disabled="busy" @click="toggleMcp(item)">
                {{ item.is_active ? '停用' : '启用' }}
              </button>
              <button class="quiet-button" type="button" :disabled="busy" @click="dropMcp(item.name)">删除</button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <p v-else-if="!mcpFormOpen" class="empty pad">
      尚未配置 MCP server。添加后工具列表自动发现，可在技能包和 Agent 中使用。
    </p>
  </section>

  <!-- LLM 供应商 -->
  <section class="panel mb">
    <div class="panel-bar">
      <h2>LLM 供应商 <span class="chip">{{ providers.length }}</span></h2>
      <button class="text-link" type="button" @click="providerFormOpen = !providerFormOpen">
        {{ providerFormOpen ? '收起' : '添加' }}
      </button>
    </div>

    <form v-if="providerFormOpen" class="trade-form inline-form" @submit.prevent="submitProvider">
      <fieldset>
        <label>
          名称
          <input v-model.trim="providerForm.name" required placeholder="openrouter" />
        </label>
        <label>
          Base URL
          <input v-model.trim="providerForm.base_url" required placeholder="https://openrouter.ai/api/v1" />
        </label>
        <label>
          API Key
          <input v-model.trim="providerForm.api_key" type="password" autocomplete="off" />
        </label>
        <label>
          协议
          <select v-model="providerForm.protocol">
            <option value="openai_compatible">OpenAI 兼容</option>
            <option value="anthropic">Anthropic</option>
          </select>
        </label>
        <label>
          默认模型
          <input v-model.trim="providerForm.model" placeholder="留空则自动取列表第一个" />
        </label>
        <label>
          专用代理
          <input v-model.trim="providerForm.proxy_url" placeholder="境外供应商填 http://172.17.0.1:7890" />
        </label>
      </fieldset>
      <div class="dialog-actions">
        <button class="quiet-button" type="button" @click="providerFormOpen = false">取消</button>
        <button class="primary-button" type="submit" :disabled="busy">保存并校验</button>
      </div>
      <p class="form-hint">
        保存时会发一次最小请求验证 Key 是否可用，校验不过不会落库。密钥用 AES-256-GCM 加密存储，
        任何接口只回末四位。
      </p>
    </form>

    <div v-if="providers.length" class="table-wrap">
      <table class="dense">
        <thead>
          <tr>
            <th>名称</th>
            <th>协议</th>
            <th>Base URL</th>
            <th>密钥</th>
            <th>默认模型</th>
            <th class="r">模型数</th>
            <th class="r">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in providers" :key="item.id">
            <td><strong>{{ item.name }}</strong></td>
            <td><span class="tag">{{ item.protocol === 'anthropic' ? 'Anthropic' : 'OpenAI 兼容' }}</span></td>
            <td class="mono dim">{{ item.base_url }}</td>
            <td class="mono">{{ item.key_last4 || '未设置' }}</td>
            <td class="mono">{{ item.default_model || '—' }}</td>
            <td class="r mono">{{ item.models.length }}</td>
            <td class="r">
              <button class="quiet-button" type="button" :disabled="busy" @click="dropProvider(item.name)">
                删除
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <p v-else-if="!providerFormOpen" class="empty pad">
      尚未配置。服务器实测 OpenRouter 与 DeepSeek 直连可达、无需代理。
    </p>
  </section>

  <!-- 定时任务 -->
  <section class="panel mb">
    <div class="panel-bar">
      <h2>定时任务 <span class="chip">{{ jobs.length }}</span></h2>
      <button class="text-link" type="button" @click="jobFormOpen = !jobFormOpen">
        {{ jobFormOpen ? '收起' : '新建' }}
      </button>
    </div>

    <form v-if="jobFormOpen" class="trade-form inline-form" @submit.prevent="submitJob">
      <fieldset>
        <label>
          名称
          <input v-model.trim="jobForm.name" required />
        </label>
        <label>
          类型
          <select v-model="jobForm.kind">
            <option value="sync">同步行情</option>
            <option value="screen">选股</option>
            <option value="backtest">回测</option>
            <option value="skill">技能模式</option>
          </select>
        </label>
        <label>
          cron
          <input v-model.trim="jobForm.cron" placeholder="35 15 * * 1-5" />
        </label>
      </fieldset>
      <label class="wide-label">
        配置 JSON
        <textarea v-model="jobForm.configText" rows="3" :placeholder="configPlaceholder" />
      </label>
      <div class="dialog-actions">
        <button class="quiet-button" type="button" @click="jobFormOpen = false">取消</button>
        <button class="primary-button" type="submit" :disabled="busy">创建</button>
      </div>
    </form>

    <div v-if="jobs.length" class="table-wrap">
      <table class="dense">
        <thead>
          <tr>
            <th>名称</th>
            <th>类型</th>
            <th>cron</th>
            <th>上次</th>
            <th>下次触发</th>
            <th class="r">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="job in jobs" :key="job.id">
            <td>
              <strong>{{ job.name }}</strong>
              <span v-if="!job.enabled" class="chip muted-chip">停用</span>
            </td>
            <td><span class="tag">{{ kindLabel(job.kind) }}</span></td>
            <td class="mono">{{ job.cron || '手动' }}</td>
            <td>
              <span :class="job.last_status === 'failed' ? 'tone-down' : ''">
                {{ statusLabel(job.last_status) }}
              </span>
              <span class="dim mono"> {{ job.last_run_at }}</span>
            </td>
            <td class="mono dim">{{ nextRunOf(job.id) }}</td>
            <td class="r">
              <button class="quiet-button" type="button" :disabled="busy" @click="fire(job)">执行</button>
              <button class="quiet-button" type="button" :disabled="busy" @click="toggle(job)">
                {{ job.enabled ? '停用' : '启用' }}
              </button>
              <button class="quiet-button" type="button" :disabled="busy" @click="dropJob(job)">删除</button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <p v-else-if="!jobFormOpen" class="empty pad">尚无任务。</p>
    <p v-if="schedule && !schedule.running" class="form-hint">
      调度器未启用（{{ schedule.reason }}）。任务仍可手动执行；线上需在容器设置
      PALACE_ENABLE_SCHEDULER=1。
    </p>
  </section>

  <!-- 执行历史 -->
  <section class="panel">
    <div class="panel-bar">
      <h2>执行历史</h2>
    </div>
    <div v-if="runs.length" class="table-wrap">
      <table class="dense">
        <thead>
          <tr>
            <th>时间</th>
            <th>任务</th>
            <th>触发</th>
            <th class="r">耗时</th>
            <th>结果</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="run in runs" :key="run.id">
            <td class="mono dim">{{ run.started_at }}</td>
            <td>{{ run.job_name }}</td>
            <td class="dim">{{ run.trigger }}</td>
            <td class="r mono">{{ run.duration_ms }} ms</td>
            <td :class="run.status === 'failed' ? 'tone-down' : ''">
              {{ statusLabel(run.status) }}
              <span v-if="run.error_text" class="dim">{{ firstLine(run.error_text) }}</span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <p v-else class="empty pad">还没有执行记录。</p>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'

import {
  CapabilityUnavailableError,
  createJob,
  deleteJob,
  deleteMcpServer,
  deleteProvider,
  getJobRuns,
  getJobs,
  getMcpServers,
  getProviders,
  getScheduleStatus,
  getSkills,
  installSkill,
  refreshMcpTools,
  removeSkill,
  runJob,
  saveMcpServer,
  saveProvider,
  toggleMcpServer,
  updateJob,
} from '@/api/quant'
import type { Job, JobKind, JobRun, LlmProvider, McpServer, ScheduleStatus, Skill } from '@/types/quant'

const skills = ref<Skill[]>([])
const providers = ref<LlmProvider[]>([])
const mcpServers = ref<McpServer[]>([])
const jobs = ref<Job[]>([])
const runs = ref<JobRun[]>([])
const schedule = ref<ScheduleStatus | null>(null)
const busy = ref(false)
const notice = ref('')
const errorText = ref('')

const providerFormOpen = ref(false)
const providerForm = reactive({
  name: '',
  base_url: '',
  api_key: '',
  protocol: 'openai_compatible' as 'openai_compatible' | 'anthropic',
  model: '',
  proxy_url: '',
})

const mcpFormOpen = ref(false)
const mcpForm = reactive({
  name: '',
  url: '',
  token: '',
  proxy_url: '',
  note: '',
  verify: true,
})

const jobFormOpen = ref(false)
const jobForm = reactive({ name: '', kind: 'sync' as JobKind, cron: '', configText: '' })

const configPlaceholder = computed(() => {
  const samples: Record<JobKind, string> = {
    sync: '{"workers": 6}',
    screen: '{"strategy": "qianlong-auction"}',
    backtest: '{"strategy": "qianlong-auction", "start": "2025-01-01", "hold_days": 1}',
    skill: '{"skill": "my-skill", "provider": "openrouter", "context": ["screen"]}',
  }
  return samples[jobForm.kind]
})

function kindLabel(kind: string): string {
  return { sync: '同步行情', screen: '选股', backtest: '回测', skill: '技能模式', compare: '横向对比', optimize: '退出扫描', prune: '清理历史' }[kind] ?? kind
}

function statusLabel(status: string): string {
  return { success: '✓ 成功', failed: '✗ 失败', running: '… 运行中', skipped: '跳过' }[status] ?? (status || '—')
}

function firstLine(text: string): string {
  return text.split('\n')[0].slice(0, 90)
}

function nextRunOf(id: string): string {
  const hit = schedule.value?.jobs.find((item) => item.id === id)
  return hit?.next_run_at?.replace('T', ' ').slice(0, 16) ?? '—'
}

async function guard<T>(task: () => Promise<T>, done?: string): Promise<T | null> {
  busy.value = true
  errorText.value = ''
  notice.value = ''
  try {
    const result = await task()
    if (done) notice.value = done
    return result
  } catch (caught: unknown) {
    errorText.value =
      caught instanceof CapabilityUnavailableError
        ? caught.message
        : caught instanceof Error
          ? caught.message
          : '请求失败'
    return null
  } finally {
    busy.value = false
  }
}

async function reload(): Promise<void> {
  await guard(async () => {
    const [s, p, m, j, r, sc] = await Promise.all([
      getSkills(),
      getProviders(),
      getMcpServers(),
      getJobs(),
      getJobRuns({ limit: 20 }),
      getScheduleStatus(),
    ])
    skills.value = s
    providers.value = p
    mcpServers.value = m
    jobs.value = j
    runs.value = r
    schedule.value = sc
  })
}

async function onUpload(event: Event): Promise<void> {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  const installed = await guard(() => installSkill(file))
  if (installed) {
    notice.value = `已安装技能 ${installed.slug}`
    await reload()
  }
}

async function dropSkill(slug: string): Promise<void> {
  await guard(() => removeSkill(slug), `已卸载 ${slug}`)
  await reload()
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
    }),
  )
  if (saved) {
    notice.value = `已保存 ${saved.name}，发现 ${saved.models.length} 个模型`
    providerFormOpen.value = false
    providerForm.api_key = ''
    await reload()
  }
}

async function dropProvider(name: string): Promise<void> {
  await guard(() => deleteProvider(name), `已删除 ${name}`)
  await reload()
}

async function submitMcp(): Promise<void> {
  const saved = await guard(() =>
    saveMcpServer({
      name: mcpForm.name,
      url: mcpForm.url,
      token: mcpForm.token || undefined,
      proxy_url: mcpForm.proxy_url,
      note: mcpForm.note,
      verify: mcpForm.verify,
    }),
  )
  if (saved) {
    notice.value = `已保存 ${saved.name}，发现 ${saved.tools.length} 个工具`
    mcpFormOpen.value = false
    Object.assign(mcpForm, { name: '', url: '', token: '', proxy_url: '', note: '', verify: true })
    await reload()
  }
}

async function refreshMcp(name: string): Promise<void> {
  const result = await guard(() => refreshMcpTools(name))
  if (result) {
    notice.value = `${name} 已刷新，${result.count} 个工具`
    await reload()
  }
}

async function toggleMcp(item: McpServer): Promise<void> {
  await guard(() => toggleMcpServer(item.name, !item.is_active))
  await reload()
}

async function dropMcp(name: string): Promise<void> {
  await guard(() => deleteMcpServer(name), `已删除 ${name}`)
  await reload()
}

async function submitJob(): Promise<void> {
  let config: Record<string, unknown> = {}
  if (jobForm.configText.trim()) {
    try {
      config = JSON.parse(jobForm.configText)
    } catch {
      errorText.value = '配置不是合法 JSON'
      return
    }
  }
  const created = await guard(() =>
    createJob({ name: jobForm.name, kind: jobForm.kind, cron: jobForm.cron, config }),
  )
  if (created) {
    notice.value = `已创建任务 ${created.name}`
    jobFormOpen.value = false
    jobForm.name = ''
    jobForm.cron = ''
    jobForm.configText = ''
    await reload()
  }
}

async function fire(job: Job): Promise<void> {
  const outcome = await guard(() => runJob(job.id))
  if (outcome) {
    notice.value =
      outcome.status === 'failed' ? `任务失败：${outcome.error ?? ''}` : `任务 ${job.name} 执行成功`
  }
  await reload()
}

async function toggle(job: Job): Promise<void> {
  await guard(() => updateJob(job.id, { enabled: !job.enabled }))
  await reload()
}

async function dropJob(job: Job): Promise<void> {
  await guard(() => deleteJob(job.id), `已删除 ${job.name}`)
  await reload()
}

onMounted(reload)
</script>
