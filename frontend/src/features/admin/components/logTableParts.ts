/**
 * 审计日志 / 登录日志两张表的共用零件。
 *
 * 两张表读的是同一条审计流（`AuditLogItem`）：行结构、倒序口径、分页参数完全一致，
 * 差别只在「问什么」——审计问谁改了什么，登录问谁在什么时候用什么方式进来的。
 * 所以共用的是**零件**（列定义工厂 / 筛选 schema 工厂 / 请求包装），不是组件：
 * 硬合成一个带 props 的万能表，只会让「审计要详情弹窗、登录要失败底色」这些
 * 各自的界面判断挤进同一份模板，读起来比抄两遍还贵。
 */
import { toast } from 'vue-sonner'

import type { AdminLogQuery } from '@/shared/api/admin'
import type { BasicFormSchema } from '@/shared/components/ui/basicFormTypes'
import type { BasicTableColumn } from '@/shared/components/ui/basicTableTypes'
import { toErrorMessage } from '@/shared/lib/errors'
import type { AdminAuditResponse } from '@/shared/types/admin'
import { OUTCOME_OPTIONS, type DictOption, logTime } from '../lib/adminDict'

/** BasicForm 的 v-model 形状：三个筛选维度都是字符串，空串即「不筛」。 */
export type LogFilters = Record<string, unknown>

export const EMPTY_LOG_FILTERS: Readonly<LogFilters> = {
  keyword: '',
  action: '',
  outcome: '',
}

// ---- 筛选 schema ---------------------------------------------------------

export interface LogFilterSchemaOptions {
  /** 关键词框的 placeholder：讲清这张表的关键词打在哪些字段上 */
  keywordPlaceholder: string
  /** 第二格的中文标题：审计叫「操作类型」，登录叫「登录方式」 */
  actionLabel: string
  actionOptions: readonly DictOption[]
  /** 第三格的中文标题：审计叫「执行结果」，登录叫「登录结果」 */
  outcomeLabel: string
  /** 审计的操作类型有十几项，需要可搜索；登录方式只有两项，开搜索框反而多一次交互 */
  actionFilterable?: boolean
}

/**
 * 三格筛选：关键词 + 动作 + 结果。下拉一律给中文选项，
 * 界面上不出现 `admin.set_role` / `ok` 这类后端机器码。
 */
export function createLogFilterSchemas(options: LogFilterSchemaOptions): BasicFormSchema[] {
  return [
    {
      field: 'keyword',
      label: '关键词',
      componentProps: {
        placeholder: options.keywordPlaceholder,
        clearable: true,
      },
    },
    {
      field: 'action',
      label: options.actionLabel,
      component: 'select',
      componentProps: {
        placeholder: '全部',
        clearable: true,
        filterable: options.actionFilterable ?? false,
        options: [...options.actionOptions],
      },
    },
    {
      field: 'outcome',
      label: options.outcomeLabel,
      component: 'select',
      componentProps: {
        placeholder: '全部',
        clearable: true,
        options: [...OUTCOME_OPTIONS],
      },
    },
  ]
}

// ---- 列定义 --------------------------------------------------------------

export interface LogColumnOptions {
  /** 操作人列的中文表头：审计叫「操作人」，登录叫「登录账号」 */
  actorLabel: string
  actorMinWidth: number
  /** 动作列的中文表头：审计叫「操作类型」，登录叫「登录方式」 */
  actionLabel: string
  actionWidth: number
  /** 登录日志的 IP 常带 IPv6，比审计留宽一点 */
  ipWidth: number
}

export interface LogColumns {
  time: BasicTableColumn
  actor: BasicTableColumn
  action: BasicTableColumn
  outcome: BasicTableColumn
  ip: BasicTableColumn
}

/**
 * 五根共用列。返回**具名对象**而不是数组：两张表的自有列（审计的「目标对象 / 详情」、
 * 登录的「备注」）插在不同位置，由各自组件按顺序摆，工厂不猜顺序。
 *
 * 三处口径固定在这里：
 * 1. 时间列 170px 居中，走 `logTime` 出秒级精度——排查异常登录靠的就是秒。
 * 2. 操作人列走 `actor` 插槽，`actor_id` 挂 tooltip 而不另起副行：行高 28px 塞不下双行。
 * 3. 动作 / 结果 / IP 都走插槽，分别渲染中文标签、中文标记与等宽 IP；
 *    等宽由插槽里的 `is-code` 给，不发明新的 `class-name`。
 */
export function createLogColumns(options: LogColumnOptions): LogColumns {
  return {
    time: {
      prop: 'occurred_at',
      label: '时间',
      width: 170,
      align: 'center',
      headerAlign: 'center',
      formatter: (row) => logTime(row.occurred_at as string),
    },
    actor: {
      prop: 'actor_name',
      label: options.actorLabel,
      minWidth: options.actorMinWidth,
      slotName: 'actor',
    },
    action: {
      prop: 'action',
      label: options.actionLabel,
      width: options.actionWidth,
      align: 'center',
      headerAlign: 'center',
      slotName: 'action',
    },
    outcome: {
      prop: 'outcome',
      label: '结果',
      width: 88,
      align: 'center',
      headerAlign: 'center',
      slotName: 'outcome',
    },
    ip: {
      prop: 'ip',
      label: '来源 IP',
      width: options.ipWidth,
      align: 'center',
      headerAlign: 'center',
      // IPv6 展开有 39 个字符，不截断就会折成两行，把 28px 的行撑到 49px。
      // 定宽列一律截断 + tooltip 看全，行高才守得住（D3 密度优先）。
      showOverflowTooltip: true,
      slotName: 'ip',
    },
  }
}

// ---- 请求包装 ------------------------------------------------------------

export interface FetchLogPageOptions {
  fetcher: (query: AdminLogQuery) => Promise<AdminAuditResponse>
  filters: LogFilters
  params: { currentPage: number; pageSize: number }
  /**
   * `server`：后端收 `action` 查询参数，直接透传；
   * `client`：后端不收，只能在**当前页内**过滤，分页总数仍报后端口径
   * （与 `UsersTab` 处理角色筛选的口径一致）。
   */
  actionMode: 'server' | 'client'
  errorMessage: string
}

/** 把 BasicTable 的 `currentPage/pageSize` 翻成后端的 `limit/offset`，并统一吞错为空页。 */
export async function fetchLogPage(
  options: FetchLogPageOptions,
): Promise<{ list: Record<string, unknown>[]; total: number }> {
  const { fetcher, filters, params, actionMode, errorMessage } = options
  const action = String(filters.action || '')
  try {
    const res = await fetcher({
      keyword: String(filters.keyword || '').trim() || undefined,
      action: actionMode === 'server' ? action || undefined : undefined,
      outcome: String(filters.outcome || '') || undefined,
      limit: params.pageSize,
      offset: (params.currentPage - 1) * params.pageSize,
    })
    const items =
      actionMode === 'client' && action
        ? res.items.filter((item) => item.action === action)
        : res.items
    return {
      list: items as unknown as Record<string, unknown>[],
      total: res.total,
    }
  } catch (caught: unknown) {
    toast.error(toErrorMessage(caught, errorMessage))
    return { list: [], total: 0 }
  }
}

// ---- detail_json ---------------------------------------------------------

/** `detail_json` 是后端存的字符串；解析不出对象就当「没有结构化内容」。 */
export function parseLogDetail(raw: unknown): Record<string, unknown> | null {
  const text = typeof raw === 'string' ? raw.trim() : ''
  if (!text) return null
  try {
    const parsed: unknown = JSON.parse(text)
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return null
    return parsed as Record<string, unknown>
  } catch {
    return null
  }
}

/**
 * 缩进后的详情文本。空对象 / 空串一律返回空串——弹窗里打一个孤零零的
 * 空 JSON 花括号不是信息，调用方应改显空态。
 */
export function formatLogDetail(raw: unknown): string {
  const text = typeof raw === 'string' ? raw.trim() : ''
  if (!text || text === '{}' || text === 'null') return ''
  try {
    const parsed: unknown = JSON.parse(text)
    if (parsed === null) return ''
    if (typeof parsed === 'object' && !Object.keys(parsed as object).length) return ''
    return JSON.stringify(parsed, null, 2)
  } catch {
    return text
  }
}
