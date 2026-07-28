"""A route class that commits the request's transaction before responding.

FastAPI runs the teardown of ``yield`` dependencies *after* the response has
been sent (changed in 0.106). The session dependency committed there, so every
write endpoint reported success before its transaction was durable. Measured on
this service, 8 of 20 registrations were not yet visible in the database at the
moment the client received ``201 Created``, and an immediate login for the new
account failed roughly a third of the time.

Committing in the route handler closes that window for every endpoint at once,
rather than relying on two dozen handlers each remembering to do it. A commit
that fails now surfaces as a 500 instead of a success the database never kept.
"""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Any

from fastapi import Request, Response
from fastapi.routing import APIRoute


class CommitRoute(APIRoute):
    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        original = super().get_route_handler()

        async def commit_before_responding(request: Request) -> Response:
            response = await original(request)
            session = getattr(request.state, "db_session", None)
            # A handler that never touched the database leaves no transaction
            # open, and read-only requests have nothing worth committing.
            if session is not None and session.in_transaction():
                if response.status_code < 400:
                    await session.commit()
                else:
                    # An error response must not keep partial writes.
                    await session.rollback()
            return response

        return commit_before_responding


__all__ = ["CommitRoute"]
