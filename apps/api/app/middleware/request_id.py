"""Request ID propagation.

Accepts an inbound `X-Request-ID` (so a trace survives a hop from the Next.js
BFF) and otherwise mints one. The value goes into the context var, the access
log, the error envelope, and the response header — which is what lets a support
ticket carrying one ID resolve to one stack trace.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.context import set_request_id
from app.shared.utils import ids

HEADER = "X-Request-ID"

# An inbound header is untrusted input that we echo back and write to logs.
# Constraining it prevents log injection and absurd header sizes.
_SAFE_ID = re.compile(r"^[A-Za-z0-9_\-]{1,64}$")


class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        inbound = request.headers.get(HEADER, "")
        request_id = inbound if _SAFE_ID.match(inbound) else ids.new_id(ids.REQUEST)

        set_request_id(request_id)
        request.state.request_id = request_id

        response = await call_next(request)
        response.headers[HEADER] = request_id
        return response
