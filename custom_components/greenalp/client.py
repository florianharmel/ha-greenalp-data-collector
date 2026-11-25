"""GreenAlp HTTP transport, independent of Home Assistant."""

import json
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

BASE_URL = "https://admin.maconso.greenalp.fr/api/v1"


class GreenAlpError(Exception):
    """Base class for errors safe to report."""


class AuthError(GreenAlpError):
    """Credentials or session rejected."""


class NetworkError(GreenAlpError):
    """Service or connection unavailable."""


class DataError(GreenAlpError):
    """Unexpected data format."""


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Client:
    def __init__(self, username, password, opener=None):
        self._username = username
        self._password = password
        self._opener = opener
        self._token = None

    def _read(self, path, media_type, *, body=None, token=None):
        headers = {"Accept": media_type}
        if body is not None:
            headers["Content-Type"] = "application/json"
        if token is not None:
            headers["Authorization"] = f"Bearer {token}"
        request = Request(BASE_URL + path, data=body, headers=headers)
        try:
            if self._opener is None:
                self._opener = build_opener(NoRedirect())
            with self._opener.open(request, timeout=30) as response:
                if response.status != 200 or response.headers.get_content_type() != media_type:
                    raise DataError("Unexpected response format")
                return response.read()
        except HTTPError as error:
            error.close()
            if error.code in (401, 403):
                raise AuthError("Authentication rejected") from None
            raise NetworkError("GreenAlp HTTP error") from None
        except (URLError, OSError):
            raise NetworkError("GreenAlp connection failed") from None

    def login(self):
        body = json.dumps({"username": self._username, "password": self._password}).encode()
        response = self._read("/auth/login", "application/json", body=body)
        try:
            token = json.loads(response)["token"]
        except (ValueError, TypeError, KeyError):
            raise DataError("Invalid login response") from None
        if not isinstance(token, str) or not token or not token.isascii() or not token.isprintable():
            raise DataError("Invalid login response")
        self._token = token

    def export(self):
        if self._token is None:
            self.login()
            return self._read("/consumption/export", "text/csv", token=self._token)
        try:
            return self._read("/consumption/export", "text/csv", token=self._token)
        except AuthError:
            self._token = None
            self.login()
            return self._read("/consumption/export", "text/csv", token=self._token)
