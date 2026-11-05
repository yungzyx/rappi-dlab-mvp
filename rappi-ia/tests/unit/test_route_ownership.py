"""Toda ruta que recibe un `user_id` (en la ruta, la query o el cuerpo) revisa que sea el de la sesión: una ruta nueva
sin control de dueño dejaría leer o escribir los datos de otra persona."""

import inspect
from typing import get_args

from fastapi.routing import APIRoute, iter_route_contexts

from rappi_ia.api import app as api
from rappi_ia.api.identity import owner_in_path, owner_in_query

# Sacar la sesión es justo lo que no puede pedir una sesión: `legacy_user_id` se reclama una sola vez.
EXEMPT = {("POST", "/session")}


def _routes():
    for context in iter_route_contexts(api.app.routes):
        if isinstance(context.original_route, APIRoute):
            yield context, context.original_route


def _takes_user_id(context, route: APIRoute) -> bool:
    params = {p.name for p in (*context.dependant.path_params, *context.dependant.query_params)}
    if "user_id" in params:
        return True
    body = route.body_field.field_info.annotation if route.body_field else None
    return any("user_id" in model.model_fields for model in _models(body))


def _models(annotation) -> list:
    """Los modelos de un cuerpo, también los de una unión (`/agent/offer`: un modelo por momento)."""
    if hasattr(annotation, "model_fields"):
        return [annotation]
    return [model for arg in get_args(annotation) for model in _models(arg)]


def _checks_owner(context, route: APIRoute) -> bool:
    calls = [d.call for d in context.dependant.dependencies]
    if owner_in_path in calls or owner_in_query in calls:
        return True
    source = inspect.getsource(route.endpoint)
    return "owner_of_body(" in source or "require_user(" in source


def test_every_route_with_a_user_id_checks_the_owner():
    with_user = [
        (method, context.path, context, route)
        for context, route in _routes()
        for method in sorted(route.methods)
        if _takes_user_id(context, route)
    ]
    paths = {path for _, path, _, _ in with_user}
    assert "/profile/{user_id}/autonomia" in paths  # los routers incluidos también se recorren
    unchecked = [
        f"{method} {path}"
        for method, path, context, route in with_user
        if (method, path) not in EXEMPT and not _checks_owner(context, route)
    ]
    assert unchecked == [], f"Rutas con user_id sin control de dueño: {unchecked}"
