"""Gunicorn worker used in production.

Uvicorn writes its own ``Server: uvicorn`` header when it serialises the
response, *after* application middleware has run. Setting the header in
middleware therefore produces ``Server: uvicorn, socialai`` rather than
replacing it, which still tells an attacker exactly which server and
(by behaviour) which version is running.

``server_header=False`` stops uvicorn emitting its own, leaving only the value
``SecurityHeadersMiddleware`` sets.

``date_header`` is left on: proxies and caches rely on it.

Used as::

    gunicorn services.identity_service.main:app \
        -k services.identity_service.worker.SecureUvicornWorker
"""

from __future__ import annotations

from uvicorn.workers import UvicornWorker


class SecureUvicornWorker(UvicornWorker):
    CONFIG_KWARGS = {
        "server_header": False,
        "proxy_headers": True,   # trust X-Forwarded-* from the platform edge
        "forwarded_allow_ips": "*",
    }


__all__ = ["SecureUvicornWorker"]
