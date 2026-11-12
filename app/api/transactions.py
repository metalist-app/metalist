from __future__ import annotations

from http import HTTPStatus
from functools import wraps
from contextlib import asynccontextmanager, nullcontext, contextmanager
import inspect
import time
from typing import Any, Awaitable, Callable, ParamSpec, TypeVar, cast, get_type_hints, overload

import anyio.to_thread
from fastapi import FastAPI, HTTPException
from app.services.bulk_operation import bulk_operation_guard
from fastapi.routing import APIRoute

from app.db.session import begin_request_transaction
from app.services.request_recovery import register_runtime_recovery
from app.services.maintenance_mode import maintenance_service
from app.services.request_history import add_wait


P = ParamSpec("P")
R = TypeVar("R")
_TRANSACTIONAL_ROUTE_MARKER = "__transactional_route__"
_READ_ONLY_ROUTE_MARKER = "__read_only_route__"
_MUTATION_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_STORAGE_TRANSITIONS = frozenset({"create_password", "remove_password", "restore_from_backup", "restore_backup", "import_backup"})


@contextmanager
def _mutation_slot():
    """A sync request's turn to change the vault: it waits for the change running, if any."""
    with bulk_operation_guard.track_mutation():
        yield


@asynccontextmanager
async def _async_mutation_slot():
    """An async request's turn, waited for in a worker thread. The wait is shielded from
    cancellation (anyio's default), so a request cancelled while waiting still gets its turn
    and gives it back: the slot is never left held."""
    waiting_since = time.perf_counter()
    await anyio.to_thread.run_sync(bulk_operation_guard.claim_mutation_slot)
    # How long it waited for its turn, for a problem report (app/services/request_history.py).
    add_wait(time.perf_counter() - waiting_since)
    try:
        yield
    finally:
        bulk_operation_guard.release_mutation_slot()


def _resolved_signature(func: Callable[..., Any]) -> inspect.Signature:
    signature = inspect.signature(func)
    resolved_hints = get_type_hints(
        func,
        globalns=func.__globals__,
        localns=None,
        include_extras=True,
    )

    # get_type_hints leaves out what has no annotation; those keep the signature's own.
    parameters = []
    for parameter in signature.parameters.values():
        if parameter.name in resolved_hints:
            parameter = parameter.replace(annotation=resolved_hints[parameter.name])
        parameters.append(parameter)
    return_annotation = signature.return_annotation
    if "return" in resolved_hints:
        return_annotation = resolved_hints["return"]
    return signature.replace(
        parameters=parameters,
        return_annotation=return_annotation,
    )


# Overloads keep each route's own type: a union parameter leaves mypy unable to tell an
# async route from a sync one returning an awaitable.
@overload
def transactional_route(func: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]: ...


@overload
def transactional_route(func: Callable[P, R]) -> Callable[P, R]: ...


def transactional_route(func: Callable[..., Any]) -> Callable[..., Any]:
    resolved_signature = _resolved_signature(func)

    if inspect.iscoroutinefunction(func):
        async_func = cast(Callable[..., Awaitable[Any]], func)

        @wraps(async_func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            async with _async_mutation_slot():
                _check_bulk_guard(func.__name__)
                with begin_request_transaction():
                    register_runtime_recovery()
                    return await async_func(*args, **kwargs)

        setattr(async_wrapper, "__signature__", resolved_signature)
        setattr(async_wrapper, _TRANSACTIONAL_ROUTE_MARKER, True)
        return async_wrapper

    sync_func = func

    @wraps(sync_func)
    def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
        # The slot first, holding nothing while it waits: an async change holding it may need
        # the lock (a bulk operation starting on the event loop takes it).
        waiting_since = time.perf_counter()
        with _mutation_slot():
            with bulk_operation_guard.lock:
                add_wait(time.perf_counter() - waiting_since)
                _check_bulk_guard(func.__name__)
                maintenance = nullcontext()
                if func.__name__ in _STORAGE_TRANSITIONS:
                    maintenance = maintenance_service.hold_for_transaction("Updating vault storage")
                with maintenance:
                    with begin_request_transaction():
                        register_runtime_recovery()
                        return sync_func(*args, **kwargs)

    setattr(sync_wrapper, "__signature__", resolved_signature)
    setattr(sync_wrapper, _TRANSACTIONAL_ROUTE_MARKER, True)
    return sync_wrapper


def serialized_read_route(func: Callable[P, R]) -> Callable[P, R]:
    """A read that walks the note tree in several steps (an export, backlinks):
    it holds the lock synchronous writes hold, so no write lands between its steps."""
    if inspect.iscoroutinefunction(func):
        raise TypeError(f"serialized_read_route needs a synchronous route: {func.__name__}")
    resolved_signature = _resolved_signature(cast(Callable[..., Any], func))

    @wraps(func)
    def serialized_wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        waiting_since = time.perf_counter()
        with bulk_operation_guard.lock:
            add_wait(time.perf_counter() - waiting_since)
            return func(*args, **kwargs)

    # FastAPI reads the route's parameters from its signature.
    setattr(serialized_wrapper, "__signature__", resolved_signature)
    return serialized_wrapper


def read_only_route(func: Callable[P, R]) -> Callable[P, R]:
    """A POST that changes nothing: it works only from what it is sent (a body too large or too
    private for a URL), so it never waits for a change or is refused while one runs. The edit
    preview was refused with a fatal "409 Conflict" while another request changed the vault (the
    maintainer, 2026-11-11). A route that reads the note tree in several steps takes
    serialized_read_route instead."""
    if inspect.iscoroutinefunction(func):
        raise TypeError(f"read_only_route needs a synchronous route: {func.__name__}")
    setattr(func, _READ_ONLY_ROUTE_MARKER, True)
    return func


def _is_marked(endpoint: Callable[..., Any], marker: str) -> bool:
    return marker in vars(endpoint) and vars(endpoint)[marker] is True


def assert_mutation_routes_wrapped(app: FastAPI) -> None:
    violations: list[str] = []

    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        if route.methods is None:
            continue

        mutation_methods = sorted(method for method in route.methods if method in _MUTATION_METHODS)
        if len(mutation_methods) == 0:
            continue

        endpoint = route.endpoint
        # The transactional wrapper marks the routes it wraps, read_only_route those that change
        # nothing; unwrapped ones have no mark.
        if _is_marked(endpoint, _TRANSACTIONAL_ROUTE_MARKER) or _is_marked(endpoint, _READ_ONLY_ROUTE_MARKER):
            continue

        violations.append(
            f"{','.join(mutation_methods)} {route.path} -> {endpoint.__module__}.{endpoint.__qualname__}",
        )

    if len(violations) == 0:
        return

    message_lines = ["Mutation routes missing @transactional_route:"]
    for violation in violations:
        message_lines.append(f"- {violation}")
    raise RuntimeError("\n".join(message_lines))


def _check_bulk_guard(endpoint_name: str) -> None:
    # Changes run one at a time: a storage change never runs beside another request's.
    if endpoint_name in _STORAGE_TRANSITIONS:
        assert bulk_operation_guard.active_mutations == 1, bulk_operation_guard.active_mutations
    # Preferences never touch notes, and every operation reads them once when it
    # starts, so saving them (e.g. the chat panel width) cannot disturb it.
    permitted = {"answer_bulk_question", "preview_cloud_privacy", "put_ai_debug_details", "put_client_preferences"}
    if bulk_operation_guard.operation_id and endpoint_name not in permitted:
        raise HTTPException(status_code=HTTPStatus.CONFLICT, detail="A bulk operation is running. Wait or cancel it before changing the app.")
