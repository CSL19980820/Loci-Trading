<script setup lang="ts">
import { Button } from '@/shared/components/ui/button'
import { Dialog, DialogClose, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/shared/components/ui/dialog'

defineProps<{ title: string; description?: string }>()
const open = defineModel<boolean>('open', { default: false })
</script>

<template>
  <Dialog v-model:open="open">
    <DialogContent class="record-details-dialog sm:max-w-3xl">
      <DialogHeader class="record-details-heading">
        <DialogTitle>{{ title }}</DialogTitle>
        <DialogDescription :class="description ? '' : 'sr-only'">{{ description || title }}</DialogDescription>
      </DialogHeader>
      <div class="record-details-body"><slot /></div>
      <DialogFooter class="record-details-footer">
        <slot name="actions" />
        <DialogClose as-child><Button access="read" variant="outline">关闭</Button></DialogClose>
      </DialogFooter>
    </DialogContent>
  </Dialog>
</template>

<style>
/* DialogContent teleports through a fragment: scope by this dialog's unique class. */
.ui-dialog.record-details-dialog[data-slot='dialog-content'] { display:flex; flex-direction:column; gap:0; padding:0; overflow:hidden; }
.record-details-heading { flex:none; padding:22px 52px 18px 24px; border-bottom:1px solid var(--border-subtle); text-align:left; }
.record-details-body { flex:1 1 auto; min-height:0; overflow:auto; overscroll-behavior:contain; padding:20px 24px; }
.record-details-footer { position:static; flex:none; margin:0; padding:12px 24px; border-top:1px solid var(--border-subtle); background:var(--surface-sunken); }
@media(max-width:640px) {
  .record-details-heading { padding:18px 46px 16px 16px; }
  .record-details-body { padding:16px; }
  .record-details-footer { padding:10px 16px; flex-direction:row; justify-content:flex-end; }
}
</style>
