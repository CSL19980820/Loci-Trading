<script setup lang="ts">
import { onUnmounted, ref } from 'vue'

import {
  getSkillRun,
  getSkillRunEvents,
  getSkills,
  installSkill,
  removeSkill,
  replySkillRun,
  startSkillRun,
  type SkillRun,
} from '@/shared/api/quant'
import EmptyState from '@/shared/components/ui/EmptyState.vue'
import Sheet from '@/shared/components/layout/Sheet.vue'
import { confirmDangerous } from '@/shared/lib/confirm'
import { dialogWidth } from '@/shared/lib/format'
import type { LlmProvider, Skill } from '@/shared/types/quant'
import { useOpsFeedback } from '../composables/useOpsFeedback'
import CodeEditor from './CodeEditor.vue'

const props = defineProps<{
  providers: LlmProvider[]
}>()

const { busy, notice, errorText, guard } = useOpsFeedback()

const skills = ref<Skill[]>([])

const skillRunOpen = ref(false)
const skillRunSkill = ref<Skill | null>(null)
const skillRunProvider = ref('')
const skillRunModel = ref('')
const skillRunConfigText = ref('')
const skillRun = ref<SkillRun | null>(null)
const skillRunReply = ref('')
const skillRunLog = ref<string[]>([])
const skillRunEventAfter = ref(0)
let skillRunPollTimer: ReturnType<typeof setInterval> | null = null

async function load(): Promise<void> {
  skills.value = await getSkills()
}

async function onUpload(event: Event): Promise<void> {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  const installed = await guard(() => installSkill(file))
  if (installed) {
    notice.value = `已安装技能 ${installed.slug}`
    await load()
  }
}

async function confirmDropSkill(slug: string): Promise<void> {
  if (!(await confirmDangerous(`确定卸载技能包「${slug}」？`, '确认卸载', '卸载'))) return
  await guard(() => removeSkill(slug), `已卸载 ${slug}`)
  await load()
}

function stopSkillRunPoll(): void {
  if (skillRunPollTimer) {
    clearInterval(skillRunPollTimer)
    skillRunPollTimer = null
  }
}

function openSkillRun(skill: Skill): void {
  skillRunSkill.value = skill
  skillRunProvider.value =
    props.providers.find((row) => row.is_default)?.name || props.providers[0]?.name || ''
  skillRunModel.value = ''
  skillRunConfigText.value = ''
  skillRun.value = null
  skillRunReply.value = ''
  skillRunLog.value = []
  skillRunEventAfter.value = 0
  skillRunOpen.value = true
}

async function refreshSkillRunEvents(runId: string): Promise<void> {
  try {
    const batch = await getSkillRunEvents(runId, skillRunEventAfter.value)
    skillRunEventAfter.value = batch.next_after
    for (const event of batch.events) {
      const type = String(event.type || '')
      if (type === 'phase') skillRunLog.value.push(`阶段 · ${event.name}`)
      else if (type === 'subagent_start') skillRunLog.value.push(`子agent 开始 · ${event.id}`)
      else if (type === 'subagent_end') {
        skillRunLog.value.push(`子agent 结束 · ${event.id} ${event.ok ? 'OK' : 'FAIL'}`)
      } else if (type === 'tool_start') skillRunLog.value.push(`工具 · ${event.name}`)
      else if (type === 'waiting_user') skillRunLog.value.push('等待老板回复…')
      else if (type === 'done') skillRunLog.value.push(`结束 · ${event.stopped_reason || ''}`)
      else if (type === 'error') skillRunLog.value.push(`错误 · ${event.message || ''}`)
    }
    if (skillRunLog.value.length > 80) {
      skillRunLog.value = skillRunLog.value.slice(-80)
    }
  } catch {
    // ignore transient poll errors
  }
}

async function pollSkillRunOnce(): Promise<void> {
  const current = skillRun.value
  if (!current?.id) return
  try {
    const latest = await getSkillRun(current.id)
    skillRun.value = latest
    await refreshSkillRunEvents(current.id)
    if (latest.status === 'done' || latest.status === 'error' || latest.status === 'waiting_user') {
      if (latest.status !== 'waiting_user') stopSkillRunPoll()
      if (latest.status === 'done') notice.value = `技能 ${latest.skill} 已完成`
      if (latest.status === 'error') errorText.value = latest.error || '技能运行失败'
    }
  } catch (caught: unknown) {
    errorText.value = caught instanceof Error ? caught.message : '轮询失败'
  }
}

function startSkillRunPoll(): void {
  stopSkillRunPoll()
  skillRunPollTimer = setInterval(() => {
    void pollSkillRunOnce()
  }, 1500)
}

async function launchSkillRun(): Promise<void> {
  const skill = skillRunSkill.value
  if (!skill || !skillRunProvider.value) return
  let config: Record<string, unknown> = {}
  if (skillRunConfigText.value.trim()) {
    try {
      config = JSON.parse(skillRunConfigText.value) as Record<string, unknown>
    } catch {
      errorText.value = 'config JSON 无效'
      return
    }
  }
  skillRunLog.value = []
  skillRunEventAfter.value = 0
  skillRunReply.value = ''
  const started = await guard(() =>
    startSkillRun(skill.slug, {
      provider: skillRunProvider.value,
      model: skillRunModel.value || undefined,
      config,
      background: true,
    }),
  )
  if (!started) return
  skillRun.value = started.run
  startSkillRunPoll()
  await pollSkillRunOnce()
}

async function sendSkillReply(text: string): Promise<void> {
  const current = skillRun.value
  const reply = text.trim()
  if (!current?.id || !reply) return
  const outcome = await guard(() => replySkillRun(current.id, reply, true))
  if (!outcome) return
  skillRun.value = outcome.run
  skillRunReply.value = ''
  startSkillRunPoll()
  await pollSkillRunOnce()
}

onUnmounted(stopSkillRunPoll)

defineExpose({ load })
</script>

<template>
  <Sheet title="技能包" :chip="skills.length">
    <template #actions>
      <label class="upload-label">
        <el-button type="primary" link tag="span">安装 zip</el-button>
        <input type="file" accept=".zip" hidden @change="onUpload" />
      </label>
    </template>

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
          <span v-if="skill.allowed_tools?.length" class="dim">
            工具 {{ skill.allowed_tools.join(', ') }}
          </span>
          <span v-if="skill.agents?.length" class="tag">{{ skill.agents.length }} agents</span>
          <span v-if="skill.policy === 'trading_voice'" class="tag">trading</span>
          <el-button
            size="small"
            type="primary"
            link
            :disabled="busy || !skill.enabled"
            @click="openSkillRun(skill)"
          >
            运行
          </el-button>
          <el-button size="small" text :disabled="busy" @click="confirmDropSkill(skill.slug)">
            卸载
          </el-button>
        </div>
      </li>
    </ul>
    <EmptyState
      v-else
      description="还没有技能包"
      reason="未安装技能包 zip"
      eta="安装后可建定时任务"
    >
      <label class="upload-label">
        <el-button type="primary" tag="span">安装 zip</el-button>
        <input type="file" accept=".zip" hidden @change="onUpload" />
      </label>
    </EmptyState>
    <p class="form-hint">
      权威位置：<code>data/skills/&lt;slug&gt;/SKILL.md</code>（复制目录即用，不写数据库）。
      YAML frontmatter 可声明 <code>tools:</code>（cli/mcp/builtin）、
      <code>agents:</code>（并行弹药）、
      <code>enabled</code> / <code>mcp_servers</code> / <code>policy: trading_voice</code>。
      「运行」走对话式 Skill Run（支持 ask_user 停等）；定时 Job 无人值守、不支持 HITL。
    </p>
  </Sheet>

  <el-dialog
    v-model="skillRunOpen"
    :title="skillRunSkill ? `运行 · ${skillRunSkill.name}` : '运行技能'"
    :width="dialogWidth()"
    destroy-on-close
    @closed="stopSkillRunPoll"
  >
    <el-form label-position="top" @submit.prevent>
      <el-form-item label="LLM 供应商" required>
        <el-select v-model="skillRunProvider" class="full" filterable placeholder="选择供应商">
          <el-option
            v-for="item in providers"
            :key="item.name"
            :label="item.name"
            :value="item.name"
          />
        </el-select>
      </el-form-item>
      <el-form-item label="模型（可选）">
        <el-input v-model.trim="skillRunModel" placeholder="留空用供应商默认模型" />
      </el-form-item>
      <el-form-item label="附加 config JSON（可选）">
        <CodeEditor
          v-model="skillRunConfigText"
          language="json"
          height="8rem"
        />
        <p class="form-hint">例：{"date":"2026-07-28","cutoff":"14:50"}</p>
      </el-form-item>
    </el-form>

    <div v-if="skillRun" class="skill-run-panel">
      <p class="mono dim">
        {{ skillRun.id }} ·
        <strong>{{ skillRun.status }}</strong>
      </p>
      <ul v-if="skillRunLog.length" class="skill-run-log">
        <li v-for="(line, index) in skillRunLog" :key="index" class="mono dim">{{ line }}</li>
      </ul>
      <div v-if="skillRun.status === 'waiting_user'" class="skill-run-ask">
        <p>{{ skillRun.pending_ask?.prompt || '请老板抉择' }}</p>
        <div v-if="skillRun.pending_ask?.options?.length" class="skill-run-options">
          <el-button
            v-for="opt in skillRun.pending_ask.options"
            :key="opt"
            size="small"
            :disabled="busy"
            @click="sendSkillReply(opt)"
          >
            {{ opt }}
          </el-button>
        </div>
        <el-input
          v-model="skillRunReply"
          type="textarea"
          :rows="2"
          placeholder="或自定义回复"
          class="mt-sm"
        />
        <el-button
          type="primary"
          class="mt-sm"
          :loading="busy"
          :disabled="!skillRunReply.trim()"
          @click="sendSkillReply(skillRunReply)"
        >
          提交回复
        </el-button>
      </div>
      <pre v-if="skillRun.result?.output" class="skill-run-output">{{ skillRun.result.output }}</pre>
      <p v-if="skillRun.error" class="tone-down">{{ skillRun.error }}</p>
    </div>

    <template #footer>
      <el-button @click="skillRunOpen = false">关闭</el-button>
      <el-button
        type="primary"
        :loading="busy"
        :disabled="!skillRunProvider || skillRun?.status === 'running'"
        @click="launchSkillRun"
      >
        {{ skillRun ? '重新运行' : '开始' }}
      </el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.skill-run-panel {
  margin-top: 0.75rem;
  padding-top: 0.75rem;
  border-top: 1px solid var(--line, #e5e7eb);
}

.skill-run-log {
  list-style: none;
  margin: 0.5rem 0;
  padding: 0;
  max-height: 8rem;
  overflow: auto;
}

.skill-run-ask {
  margin: 0.75rem 0;
  padding: 0.75rem;
  background: var(--panel-muted, #f8fafc);
  border-radius: 6px;
}

.skill-run-options {
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem;
  margin-top: 0.5rem;
}

.skill-run-output {
  margin-top: 0.75rem;
  max-height: 14rem;
  overflow: auto;
  white-space: pre-wrap;
  font-size: 0.8rem;
  background: var(--panel-muted, #f8fafc);
  padding: 0.75rem;
  border-radius: 6px;
}

.mt-sm {
  margin-top: 0.5rem;
}

.upload-label {
  cursor: pointer;
}

.full {
  width: 100%;
}
</style>
