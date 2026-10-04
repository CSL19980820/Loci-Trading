<script setup lang="ts">
import { ref, watch } from 'vue'
import { Radar } from '@lucide/vue'
import StrategyFootprint from './StrategyFootprint.vue'
import type { FootprintLane } from '../composables/useStrategyFootprints'
import { Button } from '@/shared/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger } from '@/shared/components/ui/dialog'

const props = withDefaults(defineProps<{
  code: string
  name: string
  lanes: FootprintLane[]
  loading: boolean
  focusDate: string
  iconOnly?: boolean
}>(), { iconOnly: false })
const emit = defineEmits<{ pick: [date: string] }>()
const open = ref(false)

watch(() => props.code, () => { open.value = false })

function pickDate(date: string): void {
  open.value = false
  emit('pick', date)
}
</script>

<template>
  <Dialog v-model:open="open">
    <DialogTrigger as-child>
      <Button
        access="read"
        variant="outline"
        :size="iconOnly ? 'icon-sm' : 'sm'"
        class="archive-footprint-toggle"
        :class="{ 'archive-footprint-toggle--icon': iconOnly }"
        aria-label="战法足迹"
        title="战法足迹"
      >
        <Radar aria-hidden="true" />
        <span v-if="!iconOnly">战法足迹</span>
      </Button>
    </DialogTrigger>
    <DialogContent class="archive-footprint-dialog sm:max-w-4xl">
      <DialogHeader>
        <DialogTitle>{{ name }} · 战法足迹</DialogTitle>
        <DialogDescription>查看各战法的历史选出记录，点击足迹日期定位 K 线。</DialogDescription>
      </DialogHeader>
      <StrategyFootprint
        :lanes="lanes"
        :loading="loading"
        :focus-date="focusDate"
        @pick="pickDate"
      />
    </DialogContent>
  </Dialog>
</template>

<style>
/* DialogContent 传送到 body，以此弹窗独有类名限制样式范围。 */
.archive-footprint-toggle { flex:none; }
.archive-footprint-toggle--icon { width:36px; height:36px; padding:0; }
.archive-footprint-dialog { display:flex; flex-direction:column; max-height:85dvh; }
.archive-footprint-dialog .fp { flex:none; }
@media(max-width:767px) {
  .archive-footprint-dialog .fp__ticks > span:nth-child(2),
  .archive-footprint-dialog .fp__ticks > span:nth-child(4) { display:none; }
}
</style>
