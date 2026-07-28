import { ElMessageBox } from 'element-plus'

/** Warning confirm; returns true if user confirmed, false if cancelled. */
export async function confirmDangerous(
  message: string,
  title = '确认',
  confirmButtonText = '确定',
): Promise<boolean> {
  try {
    await ElMessageBox.confirm(message, title, {
      type: 'warning',
      confirmButtonText,
      cancelButtonText: '取消',
    })
    return true
  } catch {
    return false
  }
}
