"""The work the server does beside the requests, with how far it got (app/services/
background_work.py): the page shows each piece as it goes (background-work-cards.js)."""

from __future__ import annotations

from typing import Dict

from fastapi import APIRouter, Request

from app.api.request_auth import require_request_auth_token
from app.services.background_work import background_work

router = APIRouter(prefix="/background-work", tags=["background-work"])


@router.get("")
def list_background_work(request: Request) -> Dict[str, object]:
    """[{key, label, done, total}] of the work running now; total 0 while not yet known."""
    require_request_auth_token(request)
    return {"work": background_work.snapshot()}
