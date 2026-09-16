import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'

/**
 * cn —— shadcn 构造的唯一类名出口。
 * clsx 管条件，twMerge 管 Tailwind 冲突收敛（例如 `px-2 px-4` 只留后者）。
 * 所有 shadcn 原语与业务页拼工具类时一律走它，不要手拼字符串。
 */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs))
}
