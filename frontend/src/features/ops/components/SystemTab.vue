<script setup lang="ts">
import { Spinner } from '@/shared/components/ui/spinner'
import { computed, nextTick, ref } from 'vue'

import { Button } from '@/shared/components/ui/button'
import { APP_RELEASED_AT, APP_VERSION } from '@/shared/lib/release'
import SettingsPanel, { type ReceiptPair } from './SettingsPanel.vue'
import SettingsSection from './SettingsSection.vue'
import SysNotifySection from './SysNotifySection.vue'
import SysSyncSection from './SysSyncSection.vue'
import { useOpsFeedback } from '../composables/useOpsFeedback'
import { useSystemSettings, type SectionStamp } from '../composables/useSystemSettings'

type SectionId = 'sync' | 'notify'

const SECTIONS: { id: SectionId; hash: string }[] = [
  { id: 'sync', hash: 'sys-sync' },
  { id: 'notify', hash: 'sys-notify' },
]

const emit = defineEmits<{
  changed: []
  'jobs-changed': []
}>()

const { busy, notice, errorText, guard } = useOpsFeedback()

const {
  wecom,
  syncMeta,
  sync,
  wecomUrl,
  wecomClearPending,
  screenTemplate,
  footNotice,
  sectionError,
  notifyDirty,
  dirty,
  dirtyLabels,
  stamps,
  load: loadDrafts,
  revertAll,
  applyRecommendedSync: fillRecommended,
  markClearWecom,
  testWecom: runTestWecom,
  saveAll: persistAll,
} = useSystemSettings()

/**
 * 「测试」什么时候真的点不动：正在忙，或者**根本没有可测的地址**
 * （既没配过、也没在输入框里填新的；或者这次改动就是要清掉它）。
 *
 * 「有未保存改动」不再算点不动——那是「保存并测试」该干的活。
 */
const testDisabled = computed(() => {
  if (busy.value) return true
  const typed = wecomUrl.value.trim() !== ''
  if (wecomClearPending.value && !typed) return true
  return !wecom.value.configured && !typed
})

const versionReceipt = computed((): ReceiptPair[] => [
  { key: '版本', value: `v${APP_VERSION}`, hint: APP_RELEASED_AT },
  { key: '发布', value: APP_RELEASED_AT },
])

const footStatus = () => {
  if (footNotice.value) return footNotice.value
  if (!dirty.value) return '无未保存改动'
  return `未保存 ${dirtyLabels.value.length} 项：${dirtyLabels.value.join(' · ')}`
}

function stampOf(id: SectionId): SectionStamp {
  return stamps.value[id]
}

async function load(): Promise<void> {
  await loadDrafts()
  const hash = window.location.hash.replace(/^#/, '')
  const hit = SECTIONS.find((row) => row.hash === hash)
  if (hit) {
    await nextTick()
    document.getElementById(hit.hash)?.scrollIntoView({ block: 'nearest' })
  }
}

async function saveAll(): Promise<void> {
  const result = await guard(async () => {
    const r = await persistAll()
    if (!r.ok) throw new Error(r.message)
    return r
  })
  if (!result) {
    if (footNotice.value) errorText.value = footNotice.value
    return
  }
  notice.value = result.message
  emit('changed')
  emit('jobs-changed')
}

async function testWecom(): Promise<void> {
  const willSave = notifyDirty.value
  const done = await guard(async () => {
    // 「配 → 存 → 测」三段式合成一次点击：有未保存改动就先存，再测。
    // 存失败就别测了——测出来的是**旧**配置的结果，只会误导。
    if (willSave) {
      const saved = await persistAll()
      if (!saved.ok) throw new Error(saved.message)
    }
    try {
      await runTestWecom()
    } catch (caught: unknown) {
      // 企微的错误码（45009 超频 / 93000 webhook 非法 …）是排查的唯一线索，
      // 后端 detail 一个字不改地带出来，只在前面补一句「这是测试推送失败」。
      const detail = caught instanceof Error ? caught.message : String(caught || '')
      throw new Error(`测试推送失败：${detail || '后台没有留下原因'}`)
    }
    return true
  })
  if (!done) return
  notice.value = willSave ? '已保存并发出测试消息' : '测试消息已发送'
  if (willSave) {
    emit('changed')
    emit('jobs-changed')
  }
}


function applyRecommendedSync(): void {
  fillRecommended()
  void nextTick(() => {
    document.getElementById('sys-sync')?.scrollIntoView({ block: 'nearest' })
  })
}

defineExpose({
  load,
  applyRecommendedSync,
  isDirty: () => dirty.value,
})
</script>

<template>
  <SettingsPanel
    title="系统"
    :receipt="versionReceipt"
  >
    <div class="sys-stack">

      <SettingsSection
        title="行情同步"
        anchor="sys-sync"
        :stamp="stampOf('sync')"
        :error="sectionError.sync"
      >
        <SysSyncSection
          :sync="sync"
          :sync-meta="syncMeta"
          @recommend="fillRecommended"
        />
      </SettingsSection>

      <SettingsSection
        title="推送"
        anchor="sys-notify"
        :stamp="stampOf('notify')"
        :error="sectionError.notify"
      >
        <SysNotifySection
          v-model:wecom-url="wecomUrl"
          v-model:screen-template="screenTemplate"
          :sync="sync"
          :wecom="wecom"
          :clear-pending="wecomClearPending"
          :test-disabled="testDisabled"
          :test-will-save="notifyDirty"
          @clear="markClearWecom"
          @test="testWecom"
        />
      </SettingsSection>

    </div>

    <template #foot>
      <span class="foot-status" role="status" :class="{ 'is-dirty': dirty }">{{ footStatus() }}</span>
      <Button variant="outline" :disabled="busy || !dirty" @click="revertAll">全部还原</Button>
      <Button :disabled="busy || !dirty" @click="saveAll">
        <Spinner v-if="busy" class="size-4 animate-spin" aria-hidden="true" />
        保存全部
      </Button>
    </template>
  </SettingsPanel>
</template>

<style scoped>
.sys-stack {
  display: flex;
  flex-direction: column;
  gap: var(--gap-4);
  width: 100%;
}

.foot-status {
  margin-right: auto;
  color: var(--text-tertiary);
  font-family: var(--mono);
  font-size: var(--fs-aux);
}

.foot-status.is-dirty {
  color: var(--seal-ink);
  font-weight: 600;
}

@media (max-width: 640px) {
  .foot-status {
    flex-basis: 100%;
  }
}
</style>
