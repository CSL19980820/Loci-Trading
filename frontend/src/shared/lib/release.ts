/** 产品版本与能力说明。
 *
 * 版本号只在用户明确要求「发新版 / bump」时才改；日常改动不升号。
 */

export interface CapabilityGroup {
  title: string
  items: string[]
}

export const APP_VERSION = '1.0.0'

/** 本版本发布时间（本地日历，YYYY-MM-DD HH:mm） */
export const APP_RELEASED_AT = '2026-07-28 16:30'

/** 本版本一句话 */
export const APP_RELEASE_SUMMARY = '多战法账本桌面端：行情台、复盘闭环、主题与托盘。'

/** 当前软件支持的能力（帮助 → 版本） */
export const APP_CAPABILITIES: CapabilityGroup[] = [
  {
    title: '日常账本',
    items: [
      '盘面：热门/连板/板块 Top5 与当日量化滚动榜',
      '账本：持仓、浮盈、现金锚点与交割绩效',
      '交割单录入与查询',
      '候选池：筛选、详情、记成交 / 写预案',
      '复盘中心与复盘记录',
      '胜率统计',
    ],
  },
  {
    title: '行情与数据',
    items: [
      '顶栏持仓实时行情（红绿涨跌）',
      '数据台：分页证券列表 + 实时快照',
      '个股日 / 周 / 月 K，MA、MACD、KDJ',
      '本机 market.db 历史日线与数据目录配置',
      '托盘悬停：指数摘要 + 持仓明细',
    ],
  },
  {
    title: '战法与量化',
    items: [
      '选股与选股历史',
      '洞察分析',
      '量化：跑选股、回测、战法配置',
      'AI 策略转换',
      '潜龙出海 / 潜龙尾盘 / 三源尾盘共振 / RSI22 次日低吸（内置目录）',
    ],
  },
  {
    title: '桌面与系统',
    items: [
      '便携 Loci.exe，数据目录可配置',
      '托盘：唤回窗口、退出',
      '系统自动分配空闲端口（不写死 8787）',
      '主题：外观 × 主色（侧栏「主题」）',
      '帮助：桌面快捷方式、数据目录、使用说明、版本',
    ],
  },
]
