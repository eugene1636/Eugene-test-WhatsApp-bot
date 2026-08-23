"""Tiny HTTP helper shared by the REST connectors.

Every non-2xx or unparseable response becomes a SourceError. Connectors never
return a partial body and never swallow an error into an empty list.
"""
from __future__ import annotations

import time
from typing import Any

import requests

from ..errors import SourceError

TIMEOUT_SECONDS = 30
RETRY_STATUSES = {429, 500, 502, 503, 504}


class RestClient:
    def __init__(
        self,
        source: str,
        base_url: str,
        headers: dict[str, str],
        *,
        session: requests.Session | None = None,
        max_attempts: int = 3,
        sleep: Any = time.sleep,
    ) -> None:
        self.source = source
        self.base_url = base_url.rstrip("/")
        self.headers = headers
        self.session = session or requests.Session()
        self.max_attempts = max_attempts
        self._sleep = sleep

    def get(self, path: str, params: dict[str, Any] | None = None) -> dict:
        return self._request("GET", path, params=params)

    def post(self, path: str, payload: dict[str, Any]) -> dict:
        return self._request("POST", path, json=payload)

    def _request(self, method: str, path: str, **kwargs: Any) -> dict:
        url = f"{self.base_url}/{path.lstrip('/')}"
        last_error = "no attempt made"
        for attempt in range(1, self.max_attempts + 1):
            try:
                response = self.session.request(
                    method, url, headers=self.headers, timeout=TIMEOUT_SECONDS, **kwargs
                )
            except requests.RequestException as exc:
                last_error = f"{type(exc).__name__} calling {path}"
            else:
                if response.status_code in RETRY_STATUSES:
                    last_error = f"HTTP {response.status_code} from {path}"
                elif response.status_code >= 400:
                    raise SourceError(
                        self.source,
                        f"HTTP {response.status_code} from {path}: "
                        f"{response.text[:200]}",
                    )
                else:
                    try:
                        return response.json()
                    except ValueError as exc:
                        raise SourceError(
                            self.source, f"non-JSON response from {path}: {exc}"
                        ) from exc
            if attempt < self.max_attempts:
                self._sleep(2**attempt)
        raise SourceError(self.source, f"{last_error} after {self.max_attempts} tries")


def post_json(source: str, url: str, payload: dict, headers: dict[str, str]) -> dict:
    try:
        response = requests.post(
            url, json=payload, headers=headers, timeout=TIMEOUT_SECONDS
        )
    except requests.RequestException as exc:
        raise SourceError(source, f"{type(exc).__name__} posting to {url}") from exc
    if response.status_code >= 400:
        raise SourceError(
            source, f"HTTP {response.status_code} posting to {url}: {response.text[:200]}"
        )
    try:
        return response.json()
    except ValueError:
        return {"status": response.status_code, "body": response.text[:200]}
