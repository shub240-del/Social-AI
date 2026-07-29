"""Gunicorn worker class for the API.

Two settings cannot be applied from application middleware:

``server_header``
    Uvicorn writes ``Server: uvicorn`` in the protocol layer, after every
    middleware has run, so a handler cannot remove or replace it. Advertising
    the exact server makes CVE matching trivial for scanners.

``proxy_headers`` / ``forwarded_allow_ips``
    Behind Railway's edge every connection originates from the proxy. Without
    these, ``request.client.host`` is the proxy address, which would put all
    users in one rate-limit bucket.
"""

from __future__ import annotations

from uvicorn.workers import UvicornWorker


class SocialAIWorker(UvicornWorker):
    CONFIG_KWARGS = {
        "server_header": False,
        "proxy_headers": True,
        # Railway terminates TLS at its edge and is the only upstream hop.
        "forwarded_allow_ips": "*",
    }
