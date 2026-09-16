<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'

import {
  getMcpQuota,
  patchWudaoSettings,
  saveWudaoMcp,
} from '@/shared/api/quant'
import HeaderStat from '@/shared/components/ui/HeaderStat.vue'
import { dialogWidth } from '@/shared/lib/format'
import type { McpQuotaSnapshot, McpServer } from '@/shared/types/quant'

const open = defineModel<boolean>({ required: true })

const props = defineProps<{
  server: McpServer | null
}>()

const emit = defineEmits<{ saved: [] }>()

const busy = ref(false)
const quota = ref<McpQuotaSnapshot | null>(null)

const form = reactive({
  url: '',
  token: '',
  expires_at: '',
  note: '',
  is_active: true,
  verify: true,
  hist_daily_primary: false,
  daily_total: 5000,
  daily_structured: 3000,
  daily_skill: 2000,
  per_minute: 50,
})

/**
 * 今日剩余额度是**读数**，不是异常：原先用 el-alert(info) 常驻在弹窗顶上，
 * 现在改成「配额上限」那一行的行内读数（HeaderStat）。
 */
const quotaRemain = computed(() => {
  if (!quota.value) return ''
  const r = quota.value.remaining
  return `${r.total}（结构化 ${r.structured} · Skill ${r.skill}）`
})

watch(open, (visible) => {
  if (!visible || !props.server) return
  Object.assign(form, {
    url: props.server.url,
    token: '',
    expires_at: props.server.expires_at || '',
    note: props.server.note || '',
    is_active: props.server.is_active,
    verify: true,
    hist_daily_primary: Boolean(props.server.hist_daily_primary),
    daily_total: props.server.quota?.daily_total ?? 5000,
    daily_structured: props.server.quota?.daily_structured ?? 3000,
    daily_skill: props.server.quota?.daily_skill ?? 2000,
    per_minute: props.server.quota?.per_minute ?? 50,
  })
  void getMcpQuota().then((row) => {
    quota.value = row
  })
})

async function submit(): Promise<void> {
  if (busy.value) return
  busy.value = true
  try {
    await saveWudaoMcp({
      url: form.url,
      token: form.token || undefined,
      expires_at: form.expires_at || undefined,
      note: form.note,
      is_active: form.is_active,
      verify: form.verify,
    })
    await patchWudaoSettings({
      hist_daily_primary: form.hist_daily_primary,
      quota: {
        daily_total: form.daily_total,
        daily_structured: form.daily_structured,
        daily_skill: form.daily_skill,
        per_minute: form.per_minute,
      },
    })
    emit('saved')
    open.value = false
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <el-dialog
    v-model="open"
    title="悟道 A 股 · 内置 MCP"
    class="ops-dialog"
    :width="dialogWidth()"
    destroy-on-close
  >
    <!--
      开篇那段「与 Cursor / Codex 同一份凭据…」是常驻介绍段，已删：
      它解释的是 API Key，就挂到 API Key 输入框的 tooltip 上。
    -->

    <el-form label-position="top">
      <el-form-item label="MCP 地址">
        <el-input v-model.trim="form.url" />
      </el-form-item>
      <el-form-item label="API Key">
        <el-tooltip
          placement="top-start"
          content="与 Cursor / Codex 同一份凭据，只存本机；未配 Key 时自动跳过，不影响其它数据源"
        >
          <el-input
            v-model.trim="form.token"
            type="password"
            show-password
            autocomplete="off"
            placeholder="留空则保留现有 Key"
          />
        </el-tooltip>
      </el-form-item>
      <el-form-item label="套餐到期日">
        <el-date-picker
          v-model="form.expires_at"
          type="date"
          value-format="YYYY-MM-DD"
          placeholder="过期后自动跳过"
          style="width: 100%"
        />
      </el-form-item>
      <el-form-item label="备注">
        <el-input v-model.trim="form.note" />
      </el-form-item>
      <el-form-item>
        <el-switch v-model="form.is_active" active-text="启用" inactive-text="停用" aria-label="启用悟道 MCP" />
      </el-form-item>
      <el-form-item>
        <el-switch
          v-model="form.hist_daily_primary"
          active-text="日 K 同步优先使用悟道（需 Key 有效）"
        />
      </el-form-item>

      <!-- 标题压成一行：配额上限 + 今日剩余读数 + 第一条控件（日总上限） -->
      <div class="quota-head">
        <h4 class="section">配额上限</h4>
        <HeaderStat v-if="quotaRemain" label="今日剩余" :value="quotaRemain" />
        <el-form-item label="日总上限" class="quota-head__item">
          <el-input-number v-model="form.daily_total" :min="0" :max="50000" />
        </el-form-item>
      </div>
      <div class="quota-grid">
        <el-form-item label="结构化采集">
          <el-input-number v-model="form.daily_structured" :min="0" :max="50000" />
        </el-form-item>
        <el-form-item label="Skill / 助手">
          <el-input-number v-model="form.daily_skill" :min="0" :max="50000" />
        </el-form-item>
        <el-form-item label="每分钟上限">
          <el-input-number v-model="form.per_minute" :min="0" :max="500" />
        </el-form-item>
      </div>
      <el-form-item>
        <el-checkbox v-model="form.verify">保存时握手并刷新工具列表</el-checkbox>
      </el-form-item>
    </el-form>

    <template #footer>
      <el-button @click="open = false">取消</el-button>
      <el-button type="primary" :loading="busy" @click="submit">保存</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
/* 标题 + 读数 + 第一条控件同排；表单项自身的下边距在这一行里清掉 */
.quota-head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--gap-2) var(--gap-3);
  margin: var(--gap-3) 0;
  padding: var(--gap-2);
  border: 1px solid var(--rule);
  border-radius: var(--radius);
  background: var(--surface-sunken);
}

.section {
  margin: 0;
  font-size: var(--fs-body);
}

/* 表单是 label-position="top"，这一项要横过来，才能与标题真的同一行 */
.quota-head__item {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  margin: 0 0 0 auto;
}



/* 三个数字项走全局 .form-grid（auto-fit minmax 自适应列数），不再手写 1fr 1fr */
.quota-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 180px), 1fr));
  gap: 0 var(--gap-3);
}
</style>
<style scoped src="./OpsDialogSurface.css"></style>
