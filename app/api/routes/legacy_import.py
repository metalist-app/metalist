"""Bringing in the old MetaList's notes (the maintainer, 2026-11-04; docs/ui/legacy-import.md).

A new MetaList finds the old MetaList's file in its data folder and offers its notes while the
namespace it opens has no notes and no password: a fresh install. Bringing them in replaces that
empty namespace, as a restore would, and the server restarts. Protected old notes protect the
namespace with the old password, or with a new one when the old one is too weak for the
password rules."""

from __future__ import annotations

import os
from http import HTTPStatus

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, SecretStr
from typing import Annotated

from app.api.deps import get_db
from app.api.request_auth import require_request_auth_token
from app.api.routes.auth import _reset_runtime_state_after_restore, _schedule_server_restart_after_restore
from app.api.transactions import transactional_route
from app.config import ACTIVE_NAMESPACE, KDF_TIME_COST
from app.data_directory import resolve_data_directory
from app.db.notes_sql import count_notes
from app.models.database import SafeSession
from app.server_runtime import resolve_namespace_launch_defaults, save_namespace_launch_profile
from app.services.auth_service import AuthService
from app.services.backup_service import resolve_live_database_path
from app.services.diagnostics import deactivate_authenticated_logging
from app.services.input_errors import InputRejected
from app.services.legacy_metalist import LegacyDatabase, any_legacy_item, find_legacy_database, legacy_password_opens
from app.services.legacy_metalist_conversion import LegacyConversionRequest, convert_legacy_into_live_namespace
from app.services.maintenance_mode import maintenance_service

router = APIRouter(prefix="/legacy-import", tags=["legacy-import"])

# As after a restore (auth.py, backups.py).
_RESTART_AFTER_CONVERSION_DELAY_SECONDS = 0.5
_INCORRECT_PASSWORD = "Incorrect password."
_NO_OLD_NOTES_OFFERED = "There are no old MetaList notes to bring in here."


class LegacyImportStatus(BaseModel):
    # Old notes found, and this namespace empty and without a password.
    offered: bool
    # Whether they need the old password; false when none is offered.
    encrypted: bool


class LegacyPasswordCheckRequest(BaseModel):
    legacy_password: SecretStr
    # The password the converted namespace would get: the old one first, then a new one.
    new_password: SecretStr


class LegacyPasswordCheck(BaseModel):
    opens: bool
    # Why new_password can't protect this MetaList; empty when it can (or the old one doesn't open).
    new_password_problems: list[str]


class ProtectedConversionRequest(BaseModel):
    legacy_password: SecretStr
    # The converted namespace's password: the old one, or a new one when that one is too weak.
    new_password: SecretStr


class ConversionResponse(BaseModel):
    message: str


def _offered_legacy_database(db: SafeSession) -> LegacyDatabase | None:
    legacy = find_legacy_database(resolve_data_directory(environ=os.environ))
    if legacy is None or AuthService(db).has_password():
        return None
    with SafeSession.allow_reads("legacy-import:count-notes"):
        note_count = count_notes(db.connection())
    if note_count != 0:
        return None
    return legacy


def _require_offered(db: SafeSession, *, encrypted: bool) -> LegacyDatabase:
    legacy = _offered_legacy_database(db)
    if legacy is None:
        raise HTTPException(status_code=HTTPStatus.CONFLICT, detail=_NO_OLD_NOTES_OFFERED)
    if legacy.encrypted and not encrypted:
        raise HTTPException(status_code=HTTPStatus.CONFLICT, detail="The old MetaList's notes are protected.")
    if encrypted and not legacy.encrypted:
        raise HTTPException(status_code=HTTPStatus.CONFLICT, detail="The old MetaList's notes are not protected.")
    return legacy


def _convert(legacy: LegacyDatabase, *, legacy_password: str | None, password: str | None) -> ConversionResponse:
    if ACTIVE_NAMESPACE is None:
        raise RuntimeError("Bringing in the old MetaList's notes needs an active namespace")
    request = LegacyConversionRequest(
        legacy=legacy,
        legacy_password=legacy_password,
        password=password,
        launch_profile=resolve_namespace_launch_defaults(namespace=ACTIVE_NAMESPACE, environ=os.environ),
        kdf_time_cost=KDF_TIME_COST,
    )
    maintenance_service.enter_maintenance("Bringing in the old MetaList's notes")
    try:
        convert_legacy_into_live_namespace(request, database_path=resolve_live_database_path())
        profile = request.launch_profile
        save_namespace_launch_profile(
            namespace=profile.namespace, port=profile.port, https_port=profile.https_port, mcp_port=profile.mcp_port,
        )
        _reset_runtime_state_after_restore()
        deactivate_authenticated_logging()
    finally:
        maintenance_service.exit_maintenance()
    _schedule_server_restart_after_restore(delay_seconds=_RESTART_AFTER_CONVERSION_DELAY_SECONDS)
    return ConversionResponse(message="The old MetaList's notes are in")


@router.get("/status", response_model=LegacyImportStatus)
def legacy_import_status(request: Request, db: Annotated[SafeSession, Depends(get_db)]) -> LegacyImportStatus:
    require_request_auth_token(request)
    legacy = _offered_legacy_database(db)
    if legacy is None:
        return LegacyImportStatus(offered=False, encrypted=False)
    return LegacyImportStatus(offered=True, encrypted=legacy.encrypted)


@router.post("/check-password", response_model=LegacyPasswordCheck)
@transactional_route
def check_legacy_password(
    request: Request, payload: LegacyPasswordCheckRequest, db: Annotated[SafeSession, Depends(get_db)],
) -> LegacyPasswordCheck:
    require_request_auth_token(request)
    legacy = _require_offered(db, encrypted=True)
    if not legacy_password_opens([any_legacy_item(legacy.path)], payload.legacy_password.get_secret_value()):
        return LegacyPasswordCheck(opens=False, new_password_problems=[])
    policy_error = AuthService.password_policy_error(payload.new_password.get_secret_value())
    if policy_error is None:
        return LegacyPasswordCheck(opens=True, new_password_problems=[])
    return LegacyPasswordCheck(opens=True, new_password_problems=[policy_error])


@router.post("/convert", response_model=ConversionResponse)
@transactional_route
def convert_legacy_metalist(request: Request, db: Annotated[SafeSession, Depends(get_db)]) -> ConversionResponse:
    require_request_auth_token(request)
    legacy = _require_offered(db, encrypted=False)
    return _convert(legacy, legacy_password=None, password=None)


@router.post("/convert-protected", response_model=ConversionResponse)
@transactional_route
def convert_protected_legacy_metalist(
    request: Request, payload: ProtectedConversionRequest, db: Annotated[SafeSession, Depends(get_db)],
) -> ConversionResponse:
    require_request_auth_token(request)
    legacy = _require_offered(db, encrypted=True)
    legacy_password = payload.legacy_password.get_secret_value()
    if not legacy_password_opens([any_legacy_item(legacy.path)], legacy_password):
        raise InputRejected(_INCORRECT_PASSWORD)
    new_password = payload.new_password.get_secret_value()
    policy_error = AuthService.password_policy_error(new_password)
    if policy_error is not None:
        raise InputRejected(policy_error)
    return _convert(legacy, legacy_password=legacy_password, password=new_password)
