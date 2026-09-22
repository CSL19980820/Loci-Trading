"""一套公共阅读路由，按分享参数加载报告数据；不开放账本查询接口。"""
import logging
import re
import sqlite3
from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse
from src.ops.application.guardian_report_share import read_shared_report
from src.ops.infrastructure.report_share_store import validate_token

PUBLIC_REPORT_PATH = re.compile(r"/shared/reports(?:/[A-Za-z0-9_-]{43})?")
logger = logging.getLogger(__name__)


def build_report_share_router() -> APIRouter:
    router = APIRouter()

    def response_for(token: str):
        try:
            validate_token(token)
        except ValueError:
            raise HTTPException(404, '分享链接不存在或已失效', headers={'Cache-Control': 'no-store'}) from None
        try:
            page = read_shared_report(token)
            if page is None:
                raise HTTPException(404, '分享链接不存在或已失效', headers={'Cache-Control': 'no-store'})
        except FileNotFoundError:
            raise HTTPException(404, '分享链接不存在或已失效', headers={'Cache-Control': 'no-store'}) from None
        except (OSError, UnicodeError, ValueError, KeyError, TypeError, sqlite3.Error) as exc:
            logger.error('shared_report_read_failed error=%s', type(exc).__name__)
            raise HTTPException(503, '报告暂时无法读取，请稍后重试',
                                headers={'Cache-Control': 'no-store'}) from None
        return HTMLResponse(page, headers={
            'Cache-Control': 'no-store', 'Referrer-Policy': 'no-referrer',
            'X-Content-Type-Options': 'nosniff',
            'X-Robots-Tag': 'noindex, nofollow, noarchive',
            'Content-Security-Policy': "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; frame-ancestors 'none'",
        })

    @router.api_route('/shared/reports', methods=['GET', 'HEAD'], include_in_schema=False)
    def report_page(token: str = ''):
        return response_for(token)

    @router.api_route('/shared/reports/{token}', methods=['GET', 'HEAD'], include_in_schema=False)
    def compatible_report_link(token: str):
        return response_for(token)

    return router
