import type { ResearchReplayComparison } from '@/shared/types/quant-research'

export type ReplayComparisonSummary = {
  matches: boolean
  label: string
  message: string
  mismatches: string[]
}

const EXECUTION_PARTS: ReadonlyArray<readonly [keyof ResearchReplayComparison['execution_matches'], string]> = [
  ['main', '主回测'],
  ['control', '随机对照'],
  ['train', '训练阶段'],
  ['oos', 'OOS 阶段'],
]

/** UI 只在全部冻结执行层结果相等时显示回放通过。 */
export function summarizeReplayComparison(
  comparison: ResearchReplayComparison,
): ReplayComparisonSummary {
  const mismatches = EXECUTION_PARTS
    .filter(([key]) => comparison.execution_matches?.[key] !== true)
    .map(([, label]) => label)
  if (comparison.matches_card_metrics !== true) mismatches.unshift('run card 指标')

  const allPartsMatch = mismatches.length === 0
  if (comparison.matches_all_recomputed_execution === true && allPartsMatch) {
    return {
      matches: true,
      label: '全部冻结执行结果一致',
      message: '回放完成，主回测、随机对照、训练和 OOS 均与冻结结果一致',
      mismatches: [],
    }
  }
  return {
    matches: false,
    label: '冻结执行结果不一致',
    message: mismatches.length
      ? `回放完成，但以下结果与冻结执行不一致：${mismatches.join('、')}`
      : '回放完成，但后端未确认全部冻结执行结果一致',
    mismatches,
  }
}
