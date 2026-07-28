<script setup lang="ts">
import { ref } from 'vue'
import { ElMessageBox } from 'element-plus'

import { getDataLocation, saveDataLocation } from '@/shared/api/quant'
import Sheet from '@/shared/components/layout/Sheet.vue'
import { formatBytes } from '../composables/opsLabels'
import { useOpsFeedback } from '../composables/useOpsFeedback'

const { busy, notice, errorText, guard } = useOpsFeedback()

const dataLoc = ref<Awaited<ReturnType<typeof getDataLocation>> | null>(null)
const dataDirInput = ref('')

async function load(): Promise<void> {
  const dl = await getDataLocation()
  dataLoc.value = dl
  dataDirInput.value = dl.data_dir
}

async function saveDataDir(): Promise<void> {
  const path = dataDirInput.value.trim()
  if (!path) {
    errorText.value = '请填写数据目录'
    return
  }
  const saved = await guard(() => saveDataLocation({ data_dir: path, setup_done: true }))
  if (!saved) return
  dataLoc.value = saved
  dataDirInput.value = saved.pending_data_dir || saved.data_dir
  sessionStorage.removeItem('loci.bootstrap.skip')
  if (saved.restart_required) {
    notice.value = saved.message || '已保存。请关闭并重新打开 Loci 使新目录生效。'
    await ElMessageBox.alert(
      saved.message ||
        '请关闭并重新打开 Loci，新数据目录才会生效。若新目录没有日 K，重启后会再次提醒初始化。',
      '需要重启',
      { confirmButtonText: '知道了', type: 'warning' },
    )
  } else {
    notice.value = saved.message || '数据目录已保存'
    if (saved.needed_bootstrap) {
      sessionStorage.removeItem('loci.bootstrap.skip')
      window.dispatchEvent(new CustomEvent('loci:setup-complete', { detail: saved }))
    }
  }
}

defineExpose({ load })
</script>

<template>
  <Sheet title="数据目录">
    <p class="form-hint">
      便携版默认把账本与行情写在程序旁边的 <code>data/</code>。可改到其他盘；保存后需重新打开 Loci。
    </p>
    <el-form label-position="top" class="sync-form" @submit.prevent="saveDataDir">
      <el-form-item label="当前目录">
        <el-input v-model="dataDirInput" />
      </el-form-item>
      <el-form-item v-if="dataLoc" label="程序目录">
        <span class="mono dim">{{ dataLoc.install_dir }}</span>
      </el-form-item>
      <el-form-item v-if="dataLoc" label="行情库大小">
        <span class="mono">{{ formatBytes(dataLoc.market_bytes) }}</span>
        <span v-if="dataLoc.needed_bootstrap" class="chip muted-chip">尚无日 K</span>
      </el-form-item>
      <el-form-item v-if="dataLoc?.discovered_dirs?.length" label="发现已有行情">
        <div class="disc-list">
          <el-button
            v-for="item in dataLoc.discovered_dirs"
            :key="item.path + item.source"
            size="small"
            @click="dataDirInput = item.path"
          >
            {{ item.label }}
          </el-button>
        </div>
      </el-form-item>
      <div class="form-actions">
        <el-button @click="dataDirInput = dataLoc?.default_dir || dataDirInput">恢复默认</el-button>
        <el-button type="primary" :loading="busy" @click="saveDataDir">保存</el-button>
      </div>
    </el-form>
  </Sheet>
</template>

<style scoped>
.disc-list {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 0.35rem;
}

.form-actions {
  display: flex;
  gap: 0.5rem;
  margin-top: 0.5rem;
}
</style>
