from __future__ import annotations

from sqlalchemy.sql.elements import ColumnElement

from ..models import Request


def format_request_reference(request: Request) -> str:
    if request.public_id is not None:
        return str(request.public_id)
    return request.id


def build_request_lookup_filter(request_ref: str) -> ColumnElement[bool]:
    if request_ref.isdigit():
        return Request.public_id == int(request_ref)
    return Request.id == request_ref
