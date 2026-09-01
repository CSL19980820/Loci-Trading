<script setup lang="ts">
import { ref } from 'vue'

import { installSkill } from '@/shared/api/quant'
import PageToolbar from '@/shared/components/layout/PageToolbar.vue'
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
  <div class="publish">
    <PageToolbar
      dense
      seamless
      note="技能包是 zip：内含 skill.yaml 与提示词，装完落在「已装」分区"
    >
      <template #actions>
        <el-button type="primary" :loading="busy" @click="pickFile">安装 Skill 包（.zip）</el-button>
      </template>
    </PageToolbar>
    <!-- 原生 file input：浏览器选文件能力，隐藏后由上方按钮触发 -->
    <input
      ref="fileInput"
      type="file"
      accept=".zip"
      hidden
      @change="onUpload"
    />
  </div>
</template>

<style scoped>
.publish {
  display: flex;
  flex-direction: column;
}
</style>
