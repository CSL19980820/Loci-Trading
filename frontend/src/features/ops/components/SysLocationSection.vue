<script setup lang="ts">
import { Label } from '@/shared/components/ui/label'
import { TriangleAlert } from '@lucide/vue'

import { Alert, AlertTitle } from '@/shared/components/ui/alert'
import { Button } from '@/shared/components/ui/button'
import { Input } from '@/shared/components/ui/input'
import type { DataLocationInfo } from '@/shared/api/quant'
import { formatBytes } from '../composables/opsLabels'

/** 数据目录一节：三条设置行（目录 / 已发现 / 程序目录），行样式由 SettingsSection 提供。 */
const dir = defineModel<string>('dir', { required: true })

defineProps<{
  dataLoc: DataLocationInfo | null
  pendingRestart?: boolean
}>()
</script>

<template>
  <form class="sys-rows" @submit.prevent>
    <div class="settings-row">
      <div class="settings-row__lead">
        <Label class="settings-row__label" for="sys-location-dir">数据目录</Label>
        <p class="settings-row__desc">更改目录后需重启。</p>
      </div>
      <div class="settings-row__control">
        <Input id="sys-location-dir" v-model="dir" aria-label="数据目录" class="directory-input" />
      </div>
      <Alert v-if="pendingRestart" class="settings-row__note restart-alert border-warn/40 bg-warn-soft text-warn-ink">
        <TriangleAlert />
        <AlertTitle class="line-clamp-none">重启 Loci 后新目录才生效</AlertTitle>
      </Alert>
    </div>
    <div v-if="dataLoc?.discovered_dirs?.length" class="settings-row">
      <div class="settings-row__lead">
        <span class="settings-row__label">已发现的目录</span>
        
      </div>
      <div class="settings-row__control">
        <Button
          v-for="item in dataLoc.discovered_dirs"
          :key="item.path + item.source"
          variant="outline"
          size="sm"
          @click="dir = item.path"
        >
          {{ item.label }}
          <span v-if="item.market_bytes" class="disc-bytes">{{ formatBytes(item.market_bytes) }}</span>
        </Button>
      </div>
    </div>
    <div v-if="dataLoc?.install_dir" class="settings-row">
      <div class="settings-row__lead">
        <span class="settings-row__label">程序目录</span>
        
      </div>
      <div class="settings-row__control">
        <code class="mono-path">{{ dataLoc.install_dir }}</code>
      </div>
    </div>
  </form>
</template>

<style scoped>
.sys-rows {
  display: flex;
  flex-direction: column;
  width: 100%;
  min-width: 0;
}

.directory-input {
  width: 100%;
  max-width: 100%;
  font-family: var(--mono);
  font-size: var(--fs-aux);
}

.disc-bytes {
  margin-left: var(--gap-1);
  color: var(--text-tertiary);
  font-family: var(--mono);
  font-size: var(--fs-kicker);
  font-variant-numeric: tabular-nums;
}

.mono-path {
  min-width: 0;
  padding: 4px 8px;
  border-radius: var(--radius-sm);
  background: var(--surface-sunken);
  color: var(--text-secondary);
  font-family: var(--mono);
  font-size: var(--fs-aux);
  overflow-wrap: anywhere;
  text-align: left;
}

.restart-alert {
  margin-top: var(--gap-1);
}
</style>
