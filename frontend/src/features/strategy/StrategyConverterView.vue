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
} from '@/shared/api/quant'
import PageHeader from '@/shared/components/layout/PageHeader.vue'
import Sheet from '@/shared/components/layout/Sheet.vue'
import { confirmDangerous } from '@/shared/lib/confirm'
import { THINKING_OPTIONS } from '@/shared/lib/llm'
import type { LlmProvider } from '@/shared/types/quant'

const providers = ref<LlmProvider[]>([])
const customStrategies = ref<{ slug: string; name: string; file: string }[]>([])
const busy = ref(false)
const error = ref('')
const notice = ref('')
const skillFormOpen = ref(false)
const skillMdResult = ref('')
const skillCollapse = ref<string[]>([])

const contextHintOptions = [
  { value: 'screen', label: '选股' },
  { value: 'positions', label: '持仓' },
  { value: 'market_coverage', label: '覆盖' },
] as const

const form = reactive({
  slug: '',
  name: '',
  source_type: 'tdx' as 'tdx' | 'description',
  source: '',
  provider: '',
  model: '',
  thinking: '',
  entry_timing: 'next_open' as 'open' | 'next_open',
})

const skillForm = reactive({
  slug: '',
  name: '',
  description: '',
  provider: '',
  model: '',
  thinking: '',
  context_hints: [] as string[],
})

const convertProviderModels = computed(() => {
  const hit = providers.value.find((item) => item.name === form.provider)
  return hit?.models ?? []
})

const skillProviderModels = computed(() => {
  const hit = providers.value.find((item) => item.name === skillForm.provider)
  return hit?.models ?? []
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
      thinking: form.thinking || undefined,
      entry_timing: form.entry_timing,
      dry_run: dryRun === true,
    }),
  )
  if (res) {
    result.value = res
    if (res.status === 'ok') {
      notice.value = `策略 ${res.slug} 已注册，可在工坊页使用`
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

async function confirmRemove(slug: string): Promise<void> {
  if (!(await confirmDangerous(`确定删除策略「${slug}」？此操作不可撤销。`, '删除确认', '删除'))) return
  await removeCustom(slug)
}

async function doGenerateSkill(): Promise<void> {
  skillMdResult.value = ''
  const res = await guard(() =>
    generateSkillMd({
      description: skillForm.description,
      slug: skillForm.slug,
      name: skillForm.name,
      provider: skillForm.provider,
      model: skillForm.model || undefined,
      thinking: skillForm.thinking || undefined,
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

<template>
  <PageHeader title="策稿" subtitle="通达信公式 / 文字描述 → 可注册 Python 策略" />

  <el-alert v-if="error" :title="error" type="error" show-icon closable class="mb" @close="error = ''" />
  <el-alert v-if="notice" :title="notice" type="success" show-icon closable class="mb" @close="notice = ''" />

  <Sheet
    v-if="customStrategies.length"
    title="已有自定义策略"
    :chip="customStrategies.length"
    margin
  >
    <el-table :data="customStrategies" size="small">
      <el-table-column label="名称" min-width="140">
        <template #default="{ row }">
          <strong>{{ row.name }}</strong>
        </template>
      </el-table-column>
      <el-table-column label="Slug" min-width="140">
        <template #default="{ row }">
          <span class="mono dim">{{ row.slug }}</span>
        </template>
      </el-table-column>
      <el-table-column label="文件" min-width="180">
        <template #default="{ row }">
          <span class="mono dim">{{ row.file }}</span>
        </template>
      </el-table-column>
      <el-table-column label="操作" align="right" width="90" fixed="right">
        <template #default="{ row }">
          <el-button size="small" text type="danger" :disabled="busy" @click="confirmRemove(row.slug)">
            删除
          </el-button>
        </template>
      </el-table-column>
    </el-table>
  </Sheet>

  <Sheet title="新建策略" margin padded>
    <el-form label-position="top" @submit.prevent="doConvert(false)">
      <div class="form-grid">
        <el-form-item label="Slug（英文+连字符）" required>
          <el-input
            v-model.trim="form.slug"
            required
            placeholder="my-golden-cross"
          />
        </el-form-item>
        <el-form-item label="策略中文名" required>
          <el-input v-model.trim="form.name" required placeholder="金叉选股" />
        </el-form-item>
        <el-form-item label="入场时点">
          <el-select v-model="form.entry_timing" style="width: 100%">
            <el-option label="次日开盘（用了当日收盘数据）" value="next_open" />
            <el-option label="当日开盘（仅用集合竞价数据）" value="open" />
          </el-select>
        </el-form-item>
        <el-form-item label="输入类型">
          <el-select v-model="form.source_type" style="width: 100%">
            <el-option label="通达信公式（.txt）" value="tdx" />
            <el-option label="文字描述" value="description" />
          </el-select>
        </el-form-item>
        <el-form-item label="LLM 供应商" required>
          <el-select v-model="form.provider" required placeholder="选择供应商…" style="width: 100%">
            <el-option
              v-for="p in providers"
              :key="p.name"
              :label="p.is_default ? `${p.name}（默认）` : p.name"
              :value="p.name"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="模型">
          <el-select
            v-model="form.model"
            clearable
            filterable
            allow-create
            default-first-option
            placeholder="供应商默认"
            style="width: 100%"
          >
            <el-option
              v-for="model in convertProviderModels"
              :key="model"
              :label="model"
              :value="model"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="思考程度">
          <el-select v-model="form.thinking" style="width: 100%">
            <el-option
              v-for="opt in THINKING_OPTIONS"
              :key="opt.value || 'off'"
              :label="opt.label"
              :value="opt.value"
            />
          </el-select>
        </el-form-item>
      </div>

      <el-form-item
        :label="form.source_type === 'tdx' ? '通达信公式（粘贴 .txt 内容）' : '策略描述（越详细越好，写清楚每个条件）'"
        required
      >
        <el-input
          v-model="form.source"
          type="textarea"
          required
          :rows="12"
          :placeholder="sourcePlaceholder"
        />
      </el-form-item>

      <div class="form-actions">
        <el-button :disabled="busy" @click="doConvert(true)">预览代码（不保存）</el-button>
        <el-button type="primary" native-type="submit" :loading="busy" :disabled="!form.provider">
          {{ busy ? '转换中…' : '转换并注册' }}
        </el-button>
      </div>
      <p class="form-hint">
        转换后 AI 生成 Python 代码，自动做语法检查 + 完整性验证后热加载注册，无需重启服务。
        「预览」模式只生成代码供人工审核，不会写入文件。
      </p>
    </el-form>
  </Sheet>

  <Sheet v-if="result" title="生成结果" :chip="statusLabel" :muted-chip="result.status !== 'ok'" margin>
    <template #actions>
      <el-button
        v-if="result.status === 'preview' || result.status === 'issues'"
        type="primary"
        :loading="busy"
        @click="saveAfterReview"
      >
        确认保存并注册
      </el-button>
    </template>

    <div v-if="result.issues?.length" class="issue-list">
      <p class="form-error">⚠ 发现以下问题，请人工确认后再保存：</p>
      <ul>
        <li v-for="issue in result.issues" :key="issue" class="tone-down">{{ issue }}</li>
      </ul>
    </div>
    <div v-if="result.error" class="form-error">{{ result.error }}</div>

    <pre v-if="result.code" class="code-block"><code>{{ result.code }}</code></pre>

    <p v-if="result.status === 'ok'" class="form-hint highlight-hint">
      ✓ 策略 {{ result.slug }} 已注册，在工坊页可以直接选股和回测。
    </p>
  </Sheet>

  <Sheet quiet margin padded>
    <el-collapse v-model="skillCollapse">
      <el-collapse-item name="skill">
        <template #title>
          <span class="skill-collapse-title">技能包生成</span>
        </template>
        <p class="form-hint">用 LLM 根据用途描述生成 SKILL.md，可复制后打包安装到设置页。</p>
        <el-button type="primary" link @click="skillFormOpen = true">展开技能包生成</el-button>
      </el-collapse-item>
    </el-collapse>
  </Sheet>

  <el-dialog v-model="skillFormOpen" title="AI 生成技能包说明" width="40rem" destroy-on-close>
    <el-form label-position="top" @submit.prevent="doGenerateSkill">
      <div class="form-grid">
        <el-form-item label="Slug" required>
          <el-input
            v-model.trim="skillForm.slug"
            required
            placeholder="daily-screen-brief"
          />
        </el-form-item>
        <el-form-item label="技能名" required>
          <el-input v-model.trim="skillForm.name" required placeholder="每日选股简报" />
        </el-form-item>
        <el-form-item label="LLM 供应商" required>
          <el-select v-model="skillForm.provider" required placeholder="选择供应商…" style="width: 100%">
            <el-option v-for="p in providers" :key="p.name" :label="p.name" :value="p.name" />
          </el-select>
        </el-form-item>
        <el-form-item label="模型">
          <el-select
            v-model="skillForm.model"
            clearable
            filterable
            allow-create
            default-first-option
            placeholder="供应商默认"
            style="width: 100%"
          >
            <el-option
              v-for="model in skillProviderModels"
              :key="model"
              :label="model"
              :value="model"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="思考程度">
          <el-select v-model="skillForm.thinking" style="width: 100%">
            <el-option
              v-for="opt in THINKING_OPTIONS"
              :key="opt.value || 'off'"
              :label="opt.label"
              :value="opt.value"
            />
          </el-select>
        </el-form-item>
      </div>

      <el-form-item label="用途描述（越详细越好）" required>
        <el-input
          v-model="skillForm.description"
          type="textarea"
          required
          :rows="6"
          placeholder="每天盘后，读取当天选股结果，简洁输出今日入选标的、理由摘要和主要风险点，格式要适合微信发送。"
        />
      </el-form-item>

      <el-form-item label="需要哪些数据">
        <el-checkbox-group v-model="skillForm.context_hints">
          <el-checkbox
            v-for="opt in contextHintOptions"
            :key="opt.value"
            :label="opt.value"
          >
            {{ opt.label }}
          </el-checkbox>
        </el-checkbox-group>
      </el-form-item>

      <div class="form-actions">
        <el-button @click="skillFormOpen = false">关闭</el-button>
        <el-button type="primary" native-type="submit" :loading="busy" :disabled="!skillForm.provider">
          {{ busy ? '生成中…' : '生成 SKILL.md' }}
        </el-button>
      </div>
    </el-form>

    <div v-if="skillMdResult" class="skill-result">
      <div class="skill-result-bar">
        <h3>生成的 SKILL.md</h3>
        <el-button size="small" @click="copySkillMd">复制</el-button>
      </div>
      <pre class="code-block"><code>{{ skillMdResult }}</code></pre>
      <p class="form-hint">
        将上方内容保存为 SKILL.md，打包成 zip（内含 SKILL.md），在设置页安装即可使用。
      </p>
    </div>
  </el-dialog>
</template>

<style scoped>
.form-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 4px;
}

.code-block {
  background: var(--panel-2);
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 14px 16px;
  overflow-x: auto;
  font: 12px/1.6 var(--mono);
  margin: 8px 0;
  white-space: pre;
}

.issue-list {
  padding: 8px 0;
}

.issue-list ul {
  margin: 4px 0;
  padding-left: 20px;
}

.skill-collapse-title {
  font-weight: 600;
}

.skill-result {
  margin-top: 16px;
  padding-top: 16px;
  border-top: 1px solid var(--line);
}

.skill-result-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 8px;
}

.skill-result-bar h3 {
  margin: 0;
  font-size: 14px;
  font-weight: 600;
}
</style>
