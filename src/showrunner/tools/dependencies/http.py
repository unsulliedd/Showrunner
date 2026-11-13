"""The HTTPS client for downloads, behind a small interface that tests replace."""

from __future__ import annotations

import ssl
import urllib.request
from contextlib import AbstractContextManager
from typing import Protocol
from urllib.parse import urlsplit

from showrunner import __version__

TIMEOUT_SECONDS = 60.0


class InsecureUrlError(ValueError):
    """A URL, or a redirect, that is not HTTPS."""


def require_https(url: str) -> None:
    if urlsplit(url).scheme != "https":
        raise InsecureUrlError(url)


class Response(Protocol):
    """What a download reads from; `urllib`'s response already has this shape."""

    @property
    def url(self) -> str: ...

    @property
    def length(self) -> int | None: ...

    def read(self, size: int = -1, /) -> bytes: ...


class Http(Protocol):
    def fetch(self, url: str, limit: int) -> bytes:
        """A small document in full, such as a release list or a checksum file; at most `limit` bytes."""
        ...

    def stream(self, url: str) -> AbstractContextManager[Response]: ...


class _HttpsOnlyRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        require_https(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class UrllibHttp:
    def __init__(self) -> None:
        self._opener = urllib.request.build_opener(
            _HttpsOnlyRedirects(), urllib.request.HTTPSHandler(context=ssl.create_default_context())
        )

    def _request(self, url: str) -> urllib.request.Request:
        require_https(url)
        # The GitHub API refuses requests without a User-Agent.
        return urllib.request.Request(url, headers={"User-Agent": f"Showrunner/{__version__}"})

    def fetch(self, url: str, limit: int) -> bytes:
        with self._opener.open(self._request(url), timeout=TIMEOUT_SECONDS) as response:
            data = response.read(limit + 1)
        if len(data) > limit:
            raise ValueError(f"{url} is larger than {limit} bytes")
        return data

    def stream(self, url: str) -> AbstractContextManager[Response]:
        return self._opener.open(self._request(url), timeout=TIMEOUT_SECONDS)
