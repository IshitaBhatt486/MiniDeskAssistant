"""
Claude Messages API over plain HTTP (20 Nov 2026), replacing the `anthropic` SDK on the robot (-17 MB, and no
compiled `jiter` DLL for Smart App Control to block). Standard library only: urllib + json.

It offers exactly the part of the SDK the robot used, with the same names, so the callers didn't change:

    client = Anthropic(max_retries=1, timeout=40.0)
    resp = client.beta.messages.create(model=..., max_tokens=..., betas=[...], **any other body field)
    resp.stop_reason, resp.usage.input_tokens, resp.content[i].type / .text / .name / .input / .id
    AuthenticationError, PermissionDeniedError, NotFoundError, RateLimitError, APIStatusError, APIConnectionError

Request: POST {ANTHROPIC_BASE_URL or https://api.anthropic.com}/v1/messages with
  x-api-key: $ANTHROPIC_API_KEY  (or, if only ANTHROPIC_AUTH_TOKEN is set, Authorization: Bearer <token>)
  anthropic-version: 2026-10-21  (what anthropic 2.8.0 sent)
  anthropic-beta: <betas joined with commas>   (the SDK's betas=[...] is a header, never part of the body)
Every other keyword argument goes into the JSON body unchanged.

Errors: the body is {"type": "error", "error": {"type": "...", "message": "..."}}. Status 401 / 403 / 404 / 429 map to
the classes above, every other non-2xx to APIStatusError (.status_code, .type, .message). Network failures and
timeouts raise APIConnectionError.
Retries (like the SDK): 408, 409, 429, >= 500 and connection errors, up to max_retries times, waiting retry-after(-ms)
when the server sends it (capped at 8 s), else 0.5 s doubled per attempt; x-should-retry: true/false overrides.

Response blocks are dicts that also allow attribute access, so `messages.append({"role": "assistant",
"content": resp.content})` sends them back exactly as received (tool use loop).
"""

from __future__ import annotations

import json
import os
import socket
import time
import urllib.error
import urllib.request

API_VERSION = "2026-10-21"
DEFAULT_BASE_URL = "https://api.anthropic.com"


class APIError(Exception):
    pass


class APIConnectionError(APIError):
    pass


class APIStatusError(APIError):
    def __init__(self, status_code, type_=None, message="", headers=None):
        super().__init__(f"{status_code} {type_ or ''}: {message}".strip())
        self.status_code, self.type, self.message, self.headers = status_code, type_, message, headers or {}


class AuthenticationError(APIStatusError):
    pass


class PermissionDeniedError(APIStatusError):
    pass


class NotFoundError(APIStatusError):
    pass


class RateLimitError(APIStatusError):
    pass


STATUS_ERRORS = {401: AuthenticationError, 403: PermissionDeniedError, 404: NotFoundError, 429: RateLimitError}


class Obj(dict):
    """A JSON object with attribute access; missing keys read as None (like optional SDK fields)."""

    def __getattr__(self, name):
        if name.endswith("_") and name[:-1] in self:     # `from_` like the SDK
            name = name[:-1]
        return self.get(name)


def _wrap(value):
    if isinstance(value, dict):
        return Obj({k: _wrap(v) for k, v in value.items()})
    if isinstance(value, list):
        return [_wrap(v) for v in value]
    return value


def _credentials(api_key=None, auth_token=None):
    api_key = api_key or os.environ.get("ANTHROPIC_API_KEY") or None
    if api_key:
        return {"x-api-key": api_key}
    auth_token = auth_token or os.environ.get("ANTHROPIC_AUTH_TOKEN") or None
    if auth_token:
        return {"authorization": f"Bearer {auth_token}"}
    return {}


class _Messages:
    def __init__(self, client):
        self._client = client

    def create(self, betas=None, **body):
        return self._client._post("/v1/messages", body, betas)


class _Beta:
    def __init__(self, client):
        self.messages = _Messages(client)


class Anthropic:
    def __init__(self, api_key=None, auth_token=None, base_url=None, max_retries=2, timeout=600.0):
        self._auth = (api_key, auth_token)
        self.base_url = (base_url or os.environ.get("ANTHROPIC_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
        self.max_retries, self.timeout = max_retries, timeout
        self.messages = _Messages(self)
        self.beta = _Beta(self)

    def _post(self, path, body, betas=None):
        headers = {"content-type": "application/json", "anthropic-version": API_VERSION,
                   "user-agent": "deskbot-claude-http/1", **_credentials(*self._auth)}
        if betas:
            headers["anthropic-beta"] = ",".join(betas)
        data = json.dumps(body).encode()
        for attempt in range(self.max_retries + 1):
            req = urllib.request.Request(self.base_url + path, data=data, headers=headers, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    return _wrap(json.loads(r.read().decode("utf-8")))
            except urllib.error.HTTPError as e:
                err = self._status_error(e)
                if attempt < self.max_retries and self._should_retry(e):
                    time.sleep(self._delay(e.headers, attempt))
                    continue
                raise err from None
            except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError) as e:
                if attempt < self.max_retries:
                    time.sleep(self._delay({}, attempt))
                    continue
                raise APIConnectionError(f"can't reach {self.base_url}: {getattr(e, 'reason', e)}") from None
        raise APIConnectionError("no attempts made")

    @staticmethod
    def _status_error(e):
        try:
            payload = json.loads(e.read().decode("utf-8", "replace"))
            inner = payload.get("error") or {}
            type_, message = inner.get("type"), inner.get("message", "")
        except Exception:
            type_, message = None, str(e.reason)
        cls = STATUS_ERRORS.get(e.code, APIStatusError)
        return cls(e.code, type_, message, dict(e.headers or {}))

    @staticmethod
    def _should_retry(e):
        flag = (e.headers or {}).get("x-should-retry")
        if flag in ("true", "false"):
            return flag == "true"
        return e.code in (408, 409, 429) or e.code >= 500

    @staticmethod
    def _delay(headers, attempt):
        try:
            if headers.get("retry-after-ms"):
                return min(8.0, float(headers["retry-after-ms"]) / 1000)
            if headers.get("retry-after"):
                return min(8.0, float(headers["retry-after"]))
        except (TypeError, ValueError):
            pass
        return min(8.0, 0.5 * 2 ** attempt)
