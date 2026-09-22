<script setup lang="ts">
import { ref } from 'vue'
import { Upload } from '@lucide/vue'

import { installSkill } from '@/shared/api/quant'
import PageToolbar from '@/shared/components/layout/PageToolbar.vue'
import { Badge } from '@/shared/components/ui/badge'
import { Button } from '@/shared/components/ui/button'
import { Card } from '@/shared/components/ui/card'
import EmptyState from '@/shared/components/ui/EmptyState.vue'
import PageBusy from '@/shared/components/ui/PageBusy.vue'
import { toErrorMessage } from '@/shared/lib/errors'

const emit = defineEmits<{
  installed: []
  notice: [message: string]
  error: [message: string]
}>()

const busy = ref(false)
const fileInput = ref<HTMLInputElement | null>(null)

function pickFile(): void {
  fileInput.value?.click()
}

async function onUpload(event: Event): Promise<void> {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  busy.value = true
  try {
    const installed = await installSkill(file)
    emit('notice', `已安装技能 ${installed.name || installed.slug}`)
    emit('installed')
  } catch (caught: unknown) {
    emit('error', toErrorMessage(caught, '安装失败'))
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <!--
    不留块标题：这个分区（「发布」Tab）里只有一件事——挑一个 zip 装上。
    原来的 Sheet 标题「安装 Skill 包」+ chip「zip」各占一行却不导航也不操作，
    整体迁到按钮文案上，口径进 note 的 ⓘ。
  -->
  <Card
    class="publish min-h-0 flex-1 gap-0 rounded-md border-line bg-surface py-0 shadow-none"
    :aria-busy="busy"
  >
    <PageToolbar
      dense
      seamless
      note="技能包是 zip：内含 skill.yaml 与提示词，装完落在「已装」分区"
    >
      <span class="text-muted-foreground text-sm font-medium">本地技能包</span>
      <Badge variant="secondary">.zip</Badge>
    </PageToolbar>
    <PageBusy v-if="busy" label="正在安装技能包…" />
    <EmptyState v-else description="尚未选择技能包" reason="选择 .zip 文件安装">
      <Button @click="pickFile">
        <Upload aria-hidden="true" />
        选择文件
      </Button>
    </EmptyState>
    <!-- 原生 file input：浏览器选文件能力，隐藏后由上方按钮触发 -->
    <input
      ref="fileInput"
      type="file"
      accept=".zip"
      hidden
      @change="onUpload"
    />
  </Card>
</template>
