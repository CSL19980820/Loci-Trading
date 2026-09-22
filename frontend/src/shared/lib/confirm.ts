import { ref } from 'vue'

/**
 * 命令式确认框（由共享确认弹窗承载）。
 *
 * 为什么不是「挂载即用」的组件调用：本仓的调用方大多是 composable / 纯 ts
 * （`useWorkbenchAbandon.ts`、`assistantSessionActions.ts`…），它们没有组件实例，
 * 拿不到 `useDialog()` 之类的上下文。所以这里用**模块级单例状态 + 壳层挂一个宿主**
 * （`shared/components/dialogs/ConfirmHost.vue`）：调用方只 await 一个 Promise，
 * 宿主负责渲染真实的 AlertDialog 并把结果 resolve 回去。
 *
 * 宿主必须在壳里挂一次（`App.vue`），否则 Promise 永远不 settle。
 */
export interface ConfirmOptions {
  /** 正文。一句话说清「点了会发生什么」，不要写「确定吗」这种没有信息的句子 */
  message: string
  title?: string
  confirmText?: string
  cancelText?: string
  /** 破坏性操作：主按钮走 `--stamp`（红绿只属于价格，所以用印章红而不是 `--down`） */
  danger?: boolean
  /** 只有「知道了」一个按钮 */
  alertOnly?: boolean
}

interface PendingConfirm extends ConfirmOptions {
  resolve: (ok: boolean) => void
}

/** 宿主读它渲染；外部只通过下面的函数入队，不要直接改 */
export const pendingConfirm = ref<PendingConfirm | null>(null)

export function confirmAction(options: ConfirmOptions): Promise<boolean> {
  // 前一个还没答完就被新请求覆盖时，把前一个当作取消，避免调用方永久挂起
  pendingConfirm.value?.resolve(false)
  return new Promise<boolean>((resolve) => {
    pendingConfirm.value = { ...options, resolve }
  })
}

/** A cancelled confirmation must not fall through to a destructive action. */
export class ConfirmationCancelled extends Error {
  constructor() { super('操作已取消'); this.name = 'ConfirmationCancelled' }
}

export async function confirmOrThrow(options: ConfirmOptions): Promise<void> {
  if (!await confirmAction(options)) throw new ConfirmationCancelled()
}

/** 宿主答完后调用 */
export function settleConfirm(ok: boolean): void {
  const pending = pendingConfirm.value
  pendingConfirm.value = null
  pending?.resolve(ok)
}

/** 破坏性操作确认；返回 true 表示用户确认 */
export function confirmDangerous(
  message: string,
  title = '确认',
  confirmButtonText = '确认',
): Promise<boolean> {
  return confirmAction({ message, title, confirmText: confirmButtonText, danger: true })
}

/** 单按钮提示。answer 恒为 true，返回值只为写法统一 */
export async function alertDialog(
  message: string,
  title = '提示',
  confirmText = '知道了',
): Promise<boolean> {
  return confirmAction({ message, title, confirmText, alertOnly: true })
}
