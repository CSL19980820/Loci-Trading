"""Administrator-only retention settings; no arbitrary deletion or database paths."""
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from src.identity import AuthContext
from src.ops.application.retention_settings import retention_snapshot, save_retention
from src.ops.domain.retention_policy import RetentionPolicy
from src.ops.infrastructure.store import OpsStore


class RetentionUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    revision: int = Field(ge=0)
    policy: RetentionPolicy


def build_retention_router(*, write_dependency) -> APIRouter:
    router = APIRouter(prefix="/api/ops/settings/retention", tags=["ops"])

    def administrator(request: Request):
        auth = getattr(request.state, "loci_auth", None)
        if not isinstance(auth, AuthContext) or not auth.user:
            raise HTTPException(401, "请先登录")
        if not auth.user.is_admin:
            raise HTTPException(403, "需要管理员权限")
        return auth.user

    @router.get("")
    def get_settings(request: Request):
        administrator(request)
        with OpsStore(None) as store:
            return retention_snapshot(store)

    @router.put("", dependencies=[Depends(write_dependency)])
    def put_settings(payload: RetentionUpdate, request: Request):
        operator = administrator(request)
        try:
            with OpsStore(None) as store:
                result = save_retention(store, payload.policy, expected_revision=payload.revision)
            # Auditing does not expose secrets and is separate from policy storage.
            from src.identity import IdentityStore
            with IdentityStore() as identity:
                identity.write_audit(action="settings.retention", actor_id=operator.id,
                                     actor_name=operator.username, target=operator.tenant_id,
                                     detail={"revision": result["revision"]})
            return result
        except PermissionError as error:
            raise HTTPException(403, str(error)) from error
        except ValueError as error:
            raise HTTPException(409, str(error)) from error

    return router
