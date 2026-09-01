"""`create_app` 开头那串启动自愈步骤。

共同点，也是它们能放在一起的理由：**每一步都可能失败，而且每一步失败都不
许拖垮进程**。所以清一色 `try/except Exception` + `logger.exception`，异常吞在
这一层——加密凭据迁移不了、Screen Skill 目录刷不出来、WebView 缓存清不掉，
都不该让整个 API 起不来（运维还得进得去页面才能修）。

别在这里加「失败就该拒绝启动」的检查：那类校验属于 `create_app` 正文
（例如生产缺 `PALACE_ALLOWED_HOSTS` 直接 `RuntimeError`），语义正好相反。
"""
import logging

from src.shared.webview_cache import purge_webview_http_cache_on_boot

logger = logging.getLogger(__name__)


def run_startup_self_heal() -> None:
    """按顺序跑完全部自愈步骤；任何一步失败只记日志，不向外抛。"""
    try:
        from src.ai import migrate_encrypted_llm_keys

        purged_llm = migrate_encrypted_llm_keys()
        if purged_llm:
            logger.info("已清除 %s 条 LLM 旧加密凭据（请在运维页重录）", purged_llm)
    except Exception:
        logger.exception("清理 LLM 旧加密凭据失败（已忽略）")
    try:
        from src.intel import migrate_encrypted_mcp_tokens

        purged_mcp = migrate_encrypted_mcp_tokens()
        if purged_mcp:
            logger.info("已清除 %s 条 MCP 旧加密凭据（请在运维页重录）", purged_mcp)
    except Exception:
        logger.exception("清理 MCP 旧加密凭据失败（已忽略）")
    try:
        from src.strategy.application.screen_skills import refresh_screen_strategy_catalog

        refresh_screen_strategy_catalog()
    except Exception:
        logger.exception("刷新 Screen Skill 战法目录失败（已忽略）")
    # 打包桌面：uvicorn 拉起 app 时清 WebView HTTP 缓存（早于 load_url）
    try:
        purge_webview_http_cache_on_boot()
    except Exception:
        logger.exception("启动时清理 WebView 缓存失败（已忽略）")
