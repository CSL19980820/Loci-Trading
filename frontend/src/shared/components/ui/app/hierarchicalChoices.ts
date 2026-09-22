import type { ChoiceEntry } from './choiceOptions'

export interface HierarchyOptions {
  label?: string; value?: string; children?: string; disabled?: string
  emitPath?: boolean; checkStrictly?: boolean; multiple?: boolean
}
/** Preserve full paths for cascades; tree values remain stable node identifiers. */
export function hierarchyChoices(items: unknown[], config: HierarchyOptions = {}, cascade = false): ChoiceEntry[] {
  const result: ChoiceEntry[] = []
  function walk(nodes: unknown[], labels: string[], values: unknown[], inheritedDisabled: boolean) {
    for (const item of nodes) {
      if (!item || typeof item !== 'object') continue
      const row = item as Record<string, unknown>
      const value = row[config.value || (cascade ? 'value' : 'id')] ?? row.value ?? row.id
      const label = String(row[config.label || 'label'] ?? row.name ?? value ?? '')
      const path = [...values, value]
      const names = [...labels, label]
      const children = row[config.children || 'children']
      const disabled = inheritedDisabled || Boolean(row[config.disabled || 'disabled'])
      const hasChildren = Array.isArray(children) && children.length > 0
      if (!hasChildren || config.checkStrictly || !cascade) {
        result.push({ value: cascade && config.emitPath !== false ? path : value, label: names.join(' / '), disabled })
      }
      if (hasChildren) walk(children, names, path, disabled)
    }
  }
  walk(items, [], [], false)
  return result
}
