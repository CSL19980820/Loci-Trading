/**
 * 侧栏「帮助」下拉的三条命令。
 *
 * 与侧栏版型无关，也不碰任何响应式状态——按 AGENTS「与 Vue 无关的纯函数不要硬包成
 * composable」，这里就是一个 async 函数。放在 AppSidebar 里时，它是唯一一段会打接口、
 * 会弹 MessageBox 的逻辑，混在版型编排中间格外扎眼。
 */
import { ElMessage, ElMessageBox } from 'element-plus'

import { createDesktopShortcut, getDataLocation } from '@/shared/api/quant'

export async function runHelpCommand(cmd: string): Promise<void> {
  try {
    if (cmd === 'shortcut') {
      const result = await createDesktopShortcut()
      ElMessage.success(`已创建：${result.shortcut}`)
      return
    }
    if (cmd === 'data') {
      const loc = await getDataLocation()
      await ElMessageBox.alert(
        `当前数据目录：\n${loc.data_dir}\n\n可在资源管理器中打开该路径；或到「设置 → 数据目录」修改。`,
        '数据目录',
        { confirmButtonText: '知道了' },
      )
      return
    }
    if (cmd === 'readme') {
      window.open('/使用说明.txt', '_blank')
      ElMessage.info('也可查看程序目录下的「使用说明.txt」')
    }
  } catch (caught: unknown) {
    ElMessage.error(caught instanceof Error ? caught.message : '操作失败')
  }
}
