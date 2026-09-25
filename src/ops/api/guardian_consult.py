"""交易员咨询：异步回答与租户内会话历史。"""
from uuid import UUID
import asyncio
import json
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from src.ledger import GuardianStore
from src.ops.application.guardian_consult import run_consultation
from src.shared.tenancy import current_tenant, tenant_scope
from src.shared.bounded_executor import BoundedExecutor, QueueFull

_CONSULT_EXECUTOR = BoundedExecutor("guardian-consult", workers=4, capacity=8, per_tenant=2)


class ConsultQuestion(BaseModel):
    model_config=ConfigDict(extra='forbid',str_strip_whitespace=True)
    conversation_id: UUID
    request_id: UUID
    message: str=Field(min_length=1,max_length=6000)
    real_context: str=Field(default='',max_length=12000)


def build_consult_router(write_dependency):
    router=APIRouter(prefix='/consultations')
    @router.get('/{conversation_id}/turns/{request_id}/stream')
    async def stream_turn(conversation_id: UUID, request_id: UUID, request: Request):
        tenant = current_tenant()
        def snapshot():
            # SQLite 连接只在线程内存活，不跨越流式等待；每次显式绑定请求租户。
            with tenant_scope(tenant), GuardianStore() as ledger:
                return ledger.consultation_turn(str(conversation_id), str(request_id))
        initial = await run_in_threadpool(snapshot)
        if initial is None:
            raise HTTPException(404, '未找到该咨询消息')
        async def events():
            turn, previous = initial, None
            interval = 0.25
            while not await request.is_disconnected():
                if turn is None:
                    return
                data = json.dumps(turn, ensure_ascii=False)
                if data != previous:
                    yield f'event: snapshot\ndata: {data}\n\n'
                    previous = data
                    interval = 0.25
                else:
                    interval = min(2.0, interval * 2)
                    yield ': keepalive\n\n'
                if turn['status'] not in {'queued', 'running'}:
                    return
                await asyncio.sleep(interval)
                turn = await run_in_threadpool(snapshot)
        return StreamingResponse(events(), media_type='text/event-stream',
                                 headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})
    @router.get('')
    def conversations():
        with GuardianStore() as ledger:
            return {'conversations':ledger.consultations()}
    @router.get('/{conversation_id}')
    def conversation(conversation_id: UUID):
        with GuardianStore() as ledger:
            result=ledger.consultation(str(conversation_id))
            if result is None:
                raise HTTPException(404,'未找到该咨询话题')
            return result
    @router.delete('/{conversation_id}')
    def delete_conversation(conversation_id: UUID, _write: Annotated[object, Depends(write_dependency)]):
        with GuardianStore() as ledger:
            try:
                ledger.consultation(str(conversation_id))
                deleted = ledger.delete_consultation(str(conversation_id))
            except ValueError as exc:
                raise HTTPException(409, str(exc)) from exc
            if not deleted:
                raise HTTPException(404, '未找到该咨询话题')
        return {'deleted': True}
    @router.post('',status_code=202)
    def ask(payload:ConsultQuestion,_write:Annotated[object,Depends(write_dependency)]):
        tenant = current_tenant()
        with GuardianStore() as ledger:
            existing = ledger.consultation_turn(str(payload.conversation_id), str(payload.request_id))
            if existing:
                # Delegate payload equality/idempotency to the persistent store even when full.
                try:
                    ledger.submit_consultation(str(payload.conversation_id), str(payload.request_id), payload.message, payload.real_context)
                except ValueError as exc:
                    raise HTTPException(409, str(exc)) from exc
                return {'conversation_id':str(payload.conversation_id),'request_id':str(payload.request_id),'status':'accepted'}
        def cancelled():
            with tenant_scope(tenant), GuardianStore() as ledger:
                if ledger.claim_consultation(str(payload.request_id)):
                    ledger.finish_consultation(str(payload.request_id), {'error': '服务关闭，排队咨询已取消，请重新提问'})
        try:
            with _CONSULT_EXECUTOR.reserve() as submit:
                with GuardianStore() as ledger:
                    try:
                        ledger.consultation(str(payload.conversation_id))
                        created = ledger.submit_consultation(str(payload.conversation_id),str(payload.request_id),payload.message,payload.real_context)
                    except ValueError as exc:
                        raise HTTPException(409,str(exc)) from exc
                if created:
                    try:
                        submit(lambda: run_consultation(tenant,str(payload.request_id)), on_cancel=cancelled)
                    except Exception:
                        cancelled()
                        raise
        except QueueFull as exc:
            raise HTTPException(429, str(exc), headers={'Retry-After': '5'}) from exc
        return {'conversation_id':str(payload.conversation_id),'request_id':str(payload.request_id),'status':'accepted'}
    return router
