#!/usr/bin/env python
"""Rewrite frontend @/ imports after DDD folder move."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(r"E:\my_space\stock-analyzer\frontend\src")

COMPONENT_MAP = {
    "AppSidebar": "shared/components/layout/AppSidebar.vue",
    "MobileBottomNav": "shared/components/layout/MobileBottomNav.vue",
    "PageHeader": "shared/components/layout/PageHeader.vue",
    "LiveTapeBar": "shared/components/layout/LiveTapeBar.vue",
    "Sheet": "shared/components/layout/Sheet.vue",
    "DataSetupDialog": "shared/components/dialogs/DataSetupDialog.vue",
    "ImportStateDialog": "shared/components/dialogs/ImportStateDialog.vue",
    "MarketBootstrapDialog": "shared/components/dialogs/MarketBootstrapDialog.vue",
    "RecordDialog": "shared/components/dialogs/RecordDialog.vue",
    "ThemeDialog": "shared/components/dialogs/ThemeDialog.vue",
    "TradeDialog": "shared/components/dialogs/TradeDialog.vue",
    "VersionDialog": "shared/components/dialogs/VersionDialog.vue",
    "KlineChart": "shared/components/charts/KlineChart.vue",
    "Sparkline": "shared/components/charts/Sparkline.vue",
    "EmptyState": "shared/components/ui/EmptyState.vue",
    "StatCard": "shared/components/ui/StatCard.vue",
    "NumText": "shared/components/ui/NumText.vue",
    "RowActions": "shared/components/ui/RowActions.vue",
}

VIEW_MAP = {
    "DashboardView": "features/ledger/DashboardView.vue",
    "JournalView": "features/ledger/JournalView.vue",
    "PoolView": "features/ledger/PoolView.vue",
    "ArchiveView": "features/ledger/ArchiveView.vue",
    "LoginView": "features/ledger/LoginView.vue",
    "DataQueryView": "features/market/DataQueryView.vue",
    "PeekView": "features/market/PeekView.vue",
    "ReviewCenterView": "features/review/ReviewCenterView.vue",
    "ReviewsView": "features/review/ReviewsView.vue",
    "WinRateView": "features/review/WinRateView.vue",
    "InsightsView": "features/review/InsightsView.vue",
    "QuantView": "features/strategy/QuantView.vue",
    "ScreenHistoryView": "features/strategy/ScreenHistoryView.vue",
    "StrategyConverterView": "features/strategy/StrategyConverterView.vue",
    "OpsView": "features/ops/OpsView.vue",
}


def rewrite(text: str) -> str:
    for name, dest in COMPONENT_MAP.items():
        text = text.replace(f"@/components/{name}.vue", f"@/{dest}")
        text = text.replace(f"@/components/{name}", f"@/{dest}")
    for name, dest in VIEW_MAP.items():
        text = text.replace(f"@/views/{name}.vue", f"@/{dest}")
    reps = [
        ("@/api/", "@/shared/api/"),
        ("@/lib/", "@/shared/lib/"),
        ("@/stores/", "@/shared/stores/"),
        ("@/plugins/", "@/shared/plugins/"),
        ("@/types/quant", "@/shared/types/quant"),
        ("from '@/types'", "from '@/shared/types/palace'"),
        ('from "@/types"', 'from "@/shared/types/palace"'),
        ("from '@/router'", "from '@/shared/router'"),
        ("import router from './router'", "import router from './shared/router'"),
        ("from './plugins/element'", "from './shared/plugins/element'"),
        ("from './lib/theme'", "from './shared/lib/theme'"),
    ]
    for old, new in reps:
        text = text.replace(old, new)
    return text


def main() -> None:
    n = 0
    for path in ROOT.rglob("*"):
        if path.suffix not in {".vue", ".ts"}:
            continue
        original = path.read_text(encoding="utf-8")
        updated = rewrite(original)
        if updated != original:
            path.write_text(updated, encoding="utf-8")
            n += 1
            print(path)
    print(f"updated {n}")


if __name__ == "__main__":
    main()
