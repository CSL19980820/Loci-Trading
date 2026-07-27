<template>
  <header class="toolbar">
    <div class="toolbar-title">
      <h1>AI 策略转换器</h1>
      <span class="muted">通达信公式 / 文字描述 → 可注册 Python 策略</span>
    </div>
  </header>

  <p v-if="error" class="error-banner" role="alert"><span>{{ error }}</span></p>
  <p v-if="notice" class="toast" role="status">{{ notice }}</p>

  <!-- 已有自定义策略 -->
  <section v-if="customStrategies.length" class="panel mb">
    <div class="panel-bar">
      <h2>已有自定义策略 <span class="chip">{{ customStrategies.length }}</span></h2>
    </div>
    <div class="table-wrap">
      <table class="dense">
        <thead><tr><th>名称</th><th>Slug</th><th>文件</th><th class="r">操作</th></tr></thead>
        <tbody>
          <tr v-for="item in customStrategies" :key="item.slug">
            <td><strong>{{ item.name }}</strong></td>
            <td class="mono dim">{{ item.slug }}</td>
            <td class="mono dim">{{ item.file }}</td>
            <td class="r">
              <button class="quiet-button" type="button" :disabled="busy" @click="removeCustom(item.slug)">删除</button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>

  <!-- 转换表单 -->
  <section class="panel mb">
    <div class="panel-bar"><h2>新建策略</h2></div>
    <form class="convert-form" @submit.prevent="doConvert(false)">
      <div class="form-grid">
        <label>
          Slug（英文+连字符）
          <input v-model.trim="form.slug" required pattern="^[a-z0-9][a-z0-9\-]*$"
                 placeholder="my-golden-cross" />
        </label>
        <label>
          策略中文名
          <input v-model.trim="form.name" required placeholder="金叉选股" />
        </label>
        <label>
          入场时点
          <select v-model="form.entry_timing">
            <option value="next_open">次日开盘（用了当日收盘数据）</option>
            <option value="open">当日开盘（仅用集合竞价数据）</option>
          </select>
        </label>
        <label>
          输入类型
          <select v-model="form.source_type">
            <option value="tdx">通达信公式（.txt）</option>
            <option value="description">文字描述</option>
          </select>
        </label>
        <label>
          LLM 供应商
          <select v-model="form.provider" required>
            <option value="">选择供应商…</option>
            <option v-for="p in providers" :key="p.name" :value="p.name">
              {{ p.name }}（{{ p.default_model || p.protocol }}）
            </option>
          </select>
        </label>
        <label>
          指定模型（留空用默认）
          <input v-model.trim="form.model" placeholder="gpt-4o / deepseek-chat" />
        </label>
      </div>

      <label class="wide-label">
        {{ form.source_type === 'tdx' ? '通达信公式（粘贴 .txt 内容）' : '策略描述（越详细越好，写清楚每个条件）' }}
        <textarea
          v-model="form.source"
          required
          rows="12"
          :placeholder="sourcePlaceholder"
        />
      </label>

      <div class="dialog-actions">
        <button class="quiet-button" type="button" :disabled="busy"
                @click="doConvert(true)">预览代码（不保存）</button>
        <button class="primary-button" type="submit" :disabled="busy || !form.provider">
          {{ busy ? '转换中…' : '转换并注册' }}
        </button>
      </div>
      <p class="form-hint">
        转换后 AI 生成 Python 代码，自动做语法检查 + 完整性验证后热加载注册，无需重启服务。
        「预览」模式只生成代码供人工审核，不会写入文件。
      </p>
    </form>
  </section>

  <!-- 生成的代码预览 / 错误 -->
  <section v-if="result" class="panel mb">
    <div class="panel-bar">
      <h2>
        生成结果
        <span class="chip" :class="statusChipClass">{{ statusLabel }}</span>
      </h2>
      <div v-if="result.status === 'preview' || result.status === 'issues'" class="toolbar-actions">
        <button class="primary-button" type="button" :disabled="busy"
                @click="saveAfterReview">确认保存并注册</button>
      </div>
    </div>

    <div v-if="result.issues?.length" class="issue-list">
      <p class="form-error">⚠ 发现以下问题，请人工确认后再保存：</p>
      <ul>
        <li v-for="issue in result.issues" :key="issue" class="tone-down">{{ issue }}</li>
      </ul>
    </div>
    <div v-if="result.error" class="form-error">{{ result.error }}</div>

    <pre v-if="result.code" class="code-block"><code>{{ result.code }}</code></pre>

    <p v-if="result.status === 'ok'" class="form-hint highlight-hint">
      ✓ 策略 {{ result.slug }} 已注册，在量化页可以直接选股和回测。
    </p>
  </section>

  <!-- AI 生成 SKILL.md -->
  <section class="panel mb">
    <div class="panel-bar">
      <h2>AI 生成技能包说明</h2>
      <button class="text-link" type="button" @click="skillFormOpen = !skillFormOpen">
        {{ skillFormOpen ? '收起' : '展开' }}
      </button>
    </div>
    <template v-if="skillFormOpen">
      <form class="convert-form" @submit.prevent="doGenerateSkill">
        <div class="form-grid">
          <label>
            Slug
            <input v-model.trim="skillForm.slug" required pattern="^[a-z0-9][a-z0-9\-]*$"
                   placeholder="daily-screen-brief" />
          </label>
          <label>
            技能名
            <input v-model.trim="skillForm.name" required placeholder="每日选股简报" />
          </label>
          <label>
            LLM 供应商
            <select v-model="skillForm.provider" required>
              <option value="">选择供应商…</option>
              <option v-for="p in providers" :key="p.name" :value="p.name">{{ p.name }}</option>
            </select>
          </label>
        </div>
        <div class="form-grid">
          <label class="wide-label">
            用途描述（越详细越好）
            <textarea v-model="skillForm.description" required rows="6"
                      placeholder="每天盘后，读取当天选股结果，简洁输出今日入选标的、理由摘要和主要风险点，格式要适合微信发送。" />
          </label>
        </div>
        <label style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:8px">
          <span style="font-size:13px;color:var(--muted)">需要哪些数据：</span>
          <label v-for="ctx in ['screen', 'positions', 'market_coverage']" :key="ctx"
                 class="checkbox-label">
            <input type="checkbox" :value="ctx" v-model="skillForm.context_hints" />
            {{ ctx }}
          </label>
        </label>
        <div class="dialog-actions">
          <button class="primary-button" type="submit" :disabled="busy || !skillForm.provider">
            {{ busy ? '生成中…' : '生成 SKILL.md' }}
          </button>
        </div>
      </form>

      <div v-if="skillMdResult" class="mt">
        <div class="panel-bar">
          <h2>生成的 SKILL.md</h2>
          <button class="quiet-button" type="button" @click="copySkillMd">复制</button>
        </div>
        <pre class="code-block"><code>{{ skillMdResult }}</code></pre>
        <p class="form-hint">
          将上方内容保存为 SKILL.md，打包成 zip（内含 SKILL.md），在运维页安装即可使用。
        </p>
      </div>
    </template>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'

import {
  CapabilityUnavailableError,
  convertStrategy,
  deleteCustomStrategy,
  generateSkillMd,
  getProviders,
  listCustomStrategies,
  saveConvertedStrategy,
} from '@/api/quant'
import type { LlmProvider } from '@/types/quant'

const providers = ref<LlmProvider[]>([])
const customStrategies = ref<{ slug: string; name: string; file: string }[]>([])
const busy = ref(false)
const error = ref('')
const notice = ref('')
const skillFormOpen = ref(false)
const skillMdResult = ref('')

const form = reactive({
  slug: '',
  name: '',
  source_type: 'tdx' as 'tdx' | 'description',
  source: '',
  provider: '',
  model: '',
  entry_timing: 'next_open' as 'open' | 'next_open',
})

const skillForm = reactive({
  slug: '',
  name: '',
  description: '',
  provider: '',
  context_hints: [] as string[],
})

const result = ref<{
  status: string; code: string; slug: string;
  issues?: string[]; error?: string; file?: string
} | null>(null)

const sourcePlaceholder = computed(() =>
  form.source_type === 'tdx'
    ? `{策略名称}
YTSL:=(3*CLOSE+LOW+OPEN+HIGH)/6;
MA5:=MA(CLOSE,5);
...
OUTPUT: 条件1 AND 条件2;`
    : `描述选股逻辑，例如：
1. 5日均线上穿20日均线（金叉）
2. 成交量大于昨日1.5倍
3. 今日不是涨停板
4. 入场：次日开盘
请尽量详细描述每个条件的数值范围。`,
)

const statusLabel = computed(() => ({
  ok: '✓ 成功注册',
  preview: '预览（未保存）',
  issues: '⚠ 有问题，请审核',
  syntax_error: '语法错误',
  load_error: '加载失败',
})[result.value?.status ?? ''] ?? result.value?.status)

const statusChipClass = computed(() =>
  result.value?.status === 'ok' ? 'tag' : 'muted-chip',
)

async function guard<T>(task: () => Promise<T>): Promise<T | null> {
  busy.value = true
  error.value = ''
  notice.value = ''
  try {
    return await task()
  } catch (e: unknown) {
    error.value =
      e instanceof CapabilityUnavailableError
        ? e.message
        : e instanceof Error
          ? e.message
          : '请求失败'
    return null
  } finally {
    busy.value = false
  }
}

async function reload(): Promise<void> {
  const [ps, cs] = await Promise.all([
    getProviders().catch(() => []),
    listCustomStrategies().catch(() => []),
  ])
  providers.value = ps
  customStrategies.value = cs
}

async function doConvert(dryRun = false): Promise<void> {
  result.value = null
  const res = await guard(() =>
    convertStrategy({
      source: form.source,
      source_type: form.source_type,
      slug: form.slug,
      name: form.name,
      provider: form.provider,
      model: form.model || undefined,
      entry_timing: form.entry_timing,
      dry_run: dryRun === true,
    }),
  )
  if (res) {
    result.value = res
    if (res.status === 'ok') {
      notice.value = `策略 ${res.slug} 已注册，可在量化页使用`
      await reload()
    }
  }
}

async function saveAfterReview(): Promise<void> {
  if (!result.value) return
  const res = await guard(() =>
    saveConvertedStrategy({ code: result.value!.code, slug: result.value!.slug }),
  )
  if (res) {
    result.value = { ...result.value, status: 'ok', ...res }
    notice.value = `策略 ${res.slug} 已保存并注册`
    await reload()
  }
}

async function removeCustom(slug: string): Promise<void> {
  await guard(() => deleteCustomStrategy(slug))
  await reload()
  notice.value = `已删除 ${slug}`
}

async function doGenerateSkill(): Promise<void> {
  skillMdResult.value = ''
  const res = await guard(() =>
    generateSkillMd({
      description: skillForm.description,
      slug: skillForm.slug,
      name: skillForm.name,
      provider: skillForm.provider,
      context_hints: skillForm.context_hints,
    }),
  )
  if (res) {
    skillMdResult.value = res.skill_md
    notice.value = 'SKILL.md 已生成，复制后打包成 zip 安装'
  }
}

async function copySkillMd(): Promise<void> {
  await navigator.clipboard.writeText(skillMdResult.value)
  notice.value = '已复制到剪贴板'
}

onMounted(reload)
</script>

<style scoped>
.convert-form { display: flex; flex-direction: column; gap: 14px; padding: 8px 0; }
.form-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 12px;
}
.form-grid label { display: flex; flex-direction: column; gap: 4px; font-size: 13px; }
.form-grid input, .form-grid select { padding: 6px 8px; border: 1px solid var(--line-2); border-radius: 6px; }
.wide-label { display: flex; flex-direction: column; gap: 4px; font-size: 13px; }
.wide-label textarea { padding: 8px; border: 1px solid var(--line-2); border-radius: 6px;
  font: 13px/1.5 var(--mono); resize: vertical; }
.code-block {
  background: var(--panel-2); border: 1px solid var(--line);
  border-radius: 8px; padding: 14px 16px; overflow-x: auto;
  font: 12px/1.6 var(--mono); margin: 8px 0; white-space: pre;
}
.issue-list { padding: 8px 0; }
.issue-list ul { margin: 4px 0; padding-left: 20px; }
.toolbar-actions { display: flex; gap: 8px; }
.mt { margin-top: 16px; }
</style>
