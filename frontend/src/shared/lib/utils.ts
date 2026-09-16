/**
 * shadcn-vue 桥接。CLI 生成的原语一律写成
 * `import { cn } from '@/shared/lib/utils'`，而本仓的实现（含注释）在 `./cn.ts`。
 * 这里只做转发，不复制实现——两份 `cn` 会立刻在 twMerge 配置上分叉。
 *
 * 不要往这个文件加别的函数：格式化走 `./format`，纯工具放 `./` 下的具名模块。
 */
export { cn } from './cn'
