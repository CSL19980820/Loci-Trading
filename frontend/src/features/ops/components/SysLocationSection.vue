<script setup lang="ts">
import type { DataLocationInfo } from '@/shared/api/quant'
import { formatBytes } from '../composables/opsLabels'

const dir = defineModel<string>('dir', { required: true })

defineProps<{
  dataLoc: DataLocationInfo | null
  pendingRestart?: boolean
}>()
</script>

<template>
  <el-form class="sys-form" label-position="right" label-width="6.5em" size="small" @submit.prevent>
    <el-form-item label="目录">
      <el-input v-model="dir" aria-label="数据目录" class="directory-input" />
    </el-form-item>
    <el-row :gutter="12">
      <el-col v-if="dataLoc?.discovered_dirs?.length" :xs="24" :lg="14">
        <el-form-item label="已发现">
          <div class="flex flex-wrap gap-1">
            <el-button
              v-for="item in dataLoc.discovered_dirs"
              :key="item.path + item.source"
              size="small"
              @click="dir = item.path"
            >
              {{ item.label }}
              <span v-if="item.market_bytes" class="disc-bytes">
                {{ formatBytes(item.market_bytes) }}
              </span>
            </el-button>
          </div>
        </el-form-item>
      </el-col>
      <el-col v-if="dataLoc?.install_dir" :xs="24" :lg="10">
        <el-form-item label="程序目录">
          <span class="mono">{{ dataLoc.install_dir }}</span>
        </el-form-item>
      </el-col>
    </el-row>
    <el-alert
      v-if="pendingRestart"
      title="重启 Loci 后新目录才生效"
      type="warning"
      show-icon
      :closable="false"
      class="restart-alert"
    />
  </el-form>
</template>

<style scoped>
/* 发现目录按钮组：自动换行，间距 4px。 */

.disc-bytes {
  margin-left: var(--gap-1);
  font-family: var(--mono);
  font-size: var(--fs-aux);
  color: var(--mist);
}

.restart-alert {
  margin-top: 1px;
}

.mono {
  font-family: var(--mono);
  font-size: var(--fs-aux);
  color: var(--mist);
  word-break: break-all;
}

.sys-form :deep(.el-form-item) {
  margin-bottom: var(--gap-2);
}

.sys-form :deep(.el-input) {
  width: 100%;
}
</style>
<style scoped>
.directory-input :deep(.el-input__inner) { font-family: var(--mono); }
.disc-bytes { font-variant-numeric: tabular-nums; }
</style>
