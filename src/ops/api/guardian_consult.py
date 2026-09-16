"""交易员咨询：异步回答与租户内会话历史。"""
from uuid import UUID
from typing import Annotated
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from src.ledger import GuardianStore
from src.ops.application.guardian_consult import run_consultation
from src.shared.tenancy import current_tenant


class ConsultQuestion(BaseModel):
    model_config=ConfigDict(extra='forbid',str_strip_whitespace=True)
    conversation_id: UUID
    request_id: UUID
    message: str=Field(min_length=1,max_length=6000)
    real_context: str=Field(default='',max_length=12000)


def build_consult_router(write_dependency):
    router=APIRouter(prefix='/consultations')
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
    @router.post('',status_code=202)
    def ask(payload:ConsultQuestion,background:BackgroundTasks,_write:Annotated[object,Depends(write_dependency)]):
        with GuardianStore() as ledger:
            try:
                # 先清理确实超过租约的中断请求，不让旧 pending 永久阻断后续咨询。
                ledger.consultation(str(payload.conversation_id))
                created=ledger.submit_consultation(str(payload.conversation_id),str(payload.request_id),payload.message,payload.real_context)
            except ValueError as exc:
                raise HTTPException(409,str(exc)) from exc
        if created:
            background.add_task(run_consultation,current_tenant(),str(payload.request_id))
        return {'conversation_id':str(payload.conversation_id),'request_id':str(payload.request_id),'status':'accepted'}
    return router
