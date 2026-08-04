<script setup lang="ts">
import { onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'

import { getDataLocation, saveDataLocation, type DataLocationInfo } from '@/shared/api/quant'

const SETUP_EVENT = 'loci:setup-complete'

const route = useRoute()
const visible = ref(false)
const saving = ref(false)
const pathInput = ref('')
const defaultDir = ref('')
const installDir = ref('')
const discovered = ref<DataLocationInfo['discovered_dirs']>([])
const error = ref('')
const restartHint = ref('')
let probedOk = false
let probeToken = 0

onUnmounted(() => {
  probeToken += 1
})

function emitReady(info?: DataLocationInfo): void {
  window.dispatchEvent(
    new CustomEvent(SETUP_EVENT, {
      detail: info || null,
    }),
  )
}

async function probe(): Promise<void> {
  const token = ++probeToken
  try {
    const info = await getDataLocation()
    if (token !== probeToken) return
    probedOk = true
    defaultDir.value = info.default_dir
    installDir.value = info.install_dir || ''
    discovered.value = info.discovered_dirs || []
    pathInput.value = info.data_dir || info.default_dir
    if (!info.needs_setup) {
      visible.value = false
      emitReady(info)
      return
    }
    visible.value = true
  } catch {
    // 未登录等：等进主界面后再试，不发 ready 以免行情向导抢跑
  }
}

async function confirm(): Promise<void> {
  if (restartHint.value) {
    visible.value = false
    return
  }
  const path = pathInput.value.trim()
  if (!path) {
    error.value = '请填写数据目录'
    return
  }
  saving.value = true
  error.value = ''
  try {
    const saved = await saveDataLocation({ data_dir: path, setup_done: true })
    if (saved.restart_required) {
      restartHint.value =
        saved.message || '已保存并初始化。请关闭并重新打开 Loci，新目录才会生效。'
      sessionStorage.removeItem('loci.bootstrap.skip')
      return
    }
    visible.value = false
    sessionStorage.removeItem('loci.bootstrap.skip')
    emitReady(saved)
  } catch (caught: unknown) {
    error.value = caught instanceof Error ? caught.message : '保存失败'
  } finally {
    saving.value = false
  }
}

onMounted(() => {
  void probe()
})

watch(
  () => route.meta.public === true,
  (isPublic) => {
    if (!isPublic && !probedOk) void probe()
  },
)
</script>

<template>
  <el-dialog
    v-model="visible"
    title="初始化数据目录"
    width="520px"
    :close-on-click-modal="false"
    :close-on-press-escape="false"
    :show-close="false"
    destroy-on-close
  >
    <p class="lead">首次使用请选择数据存放位置。确认后会自动创建目录与账本 / 行情 / 运维三库。</p>
    <p class="hint">
      默认在程序安装目录旁的 <code>data/</code
      >（当前程序目录：<code>{{ installDir || '…' }}</code>）。可改到其他盘；改路径后需重新打开程序才生效。
    </p>

    <el-form label-position="top" class="form" @submit.prevent="confirm">
      <el-form-item label="数据目录">
        <el-input v-model="pathInput" placeholder="绝对路径，例如 D:\Loci\data" />
      </el-form-item>
      <el-form-item v-if="defaultDir" label="使用默认（程序旁）">
        <el-button text type="primary" @click="pathInput = defaultDir">{{ defaultDir }}</el-button>
      </el-form-item>
      <el-form-item v-if="discovered.length" label="发现已有行情">
        <div class="discovered">
          <el-button
            v-for="item in discovered"
            :key="item.path + item.source"
            class="disc-btn"
            @click="pathInput = item.path"
          >
            {{ item.label }}
          </el-button>
        </div>
      </el-form-item>
    </el-form>

    <el-alert
      v-if="error"
      :title="error"
      type="error"
      show-icon
      :closable="false"
      class="mb"
    />
    <el-alert
      v-if="restartHint"
      :title="restartHint"
      type="warning"
      show-icon
      :closable="false"
      class="mb"
    />

    <template #footer>
      <el-button type="primary" :loading="saving" @click="confirm">
        {{ restartHint ? '知道了' : '确认并初始化' }}
      </el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.lead {
  margin: 0 0 0.5rem;
  line-height: 1.5;
}
.hint {
  margin: 0 0 1rem;
  color: var(--el-text-color-secondary);
  font-size: 0.85rem;
  line-height: 1.45;
}
.form {
  margin-top: 0.5rem;
}
.discovered {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 0.35rem;
}
.disc-btn {
  height: auto;
  padding: 0.35rem 0.5rem;
  white-space: normal;
  text-align: left;
  line-height: 1.35;
}
.mb {
  margin-top: 0.75rem;
}
code {
  font-size: 0.85em;
}
</style>
