"""Thin wrapper around the Qonto Business API.

Read-only: the client fetches the organization and its transactions, nothing
else. It never sends anything that could move money.

The API secret must never leave this module. It is put into a request header
and nowhere else -- not into log messages, not into exceptions, not into the
repr of this class.
"""

import time
from collections.abc import Iterator
from datetime import date, datetime
from typing import Any

import frappe
import requests
from frappe import _

PRODUCTION_BASE_URL = "https://thirdparty.qonto.com"
SANDBOX_BASE_URL = "https://thirdparty-sandbox.staging.qonto.co"

CONNECT_TIMEOUT = 10
READ_TIMEOUT = 30

MAX_ATTEMPTS = 3
BACKOFF_SECONDS = 1.0
RETRY_STATUS_CODES = frozenset({429, 500, 502, 503, 504})

PER_PAGE = 100
MAX_BODY_CHARS = 1000


class QontoApiError(frappe.ValidationError):
	"""An API response we cannot recover from.

	Carries the HTTP status code and a truncated response body so the caller
	can write something useful into the sync log. Qonto echoes neither the
	Authorization header nor the staging token, so the body is safe to store.
	"""

	def __init__(self, message: str, status_code: int | None = None, body: str | None = None):
		super().__init__(message)
		self.status_code = status_code
		self.body = body


def _format_timestamp(value: Any) -> str | None:
	"""Render a date/datetime the way the Qonto API expects it (ISO 8601, UTC)."""
	if value is None:
		return None
	if isinstance(value, str):
		return value
	if isinstance(value, datetime):
		return value.strftime("%Y-%m-%dT%H:%M:%S.000Z")
	if isinstance(value, date):
		return f"{value.isoformat()}T00:00:00.000Z"
	return str(value)


class QontoClient:
	def __init__(
		self,
		login: str,
		secret_key: str,
		sandbox_mode: bool = False,
		staging_token: str | None = None,
		session: Any = None,
	):
		if not login or not secret_key:
			frappe.throw(
				_("Qonto API login and secret key are required."),
				title=_("Qonto is not configured"),
			)

		self.login = login
		self._secret_key = secret_key
		self.sandbox_mode = bool(sandbox_mode)
		self._staging_token = staging_token
		self.base_url = SANDBOX_BASE_URL if self.sandbox_mode else PRODUCTION_BASE_URL

		self.session = session if session is not None else requests.Session()
		self.session.headers.update(self._auth_headers())

	@classmethod
	def from_settings(cls, settings: Any = None, session: Any = None) -> "QontoClient":
		"""Build a client from the Qonto Settings single doc.

		Secrets are read through get_password(), never off the document.
		"""
		settings = settings or frappe.get_single("Qonto Settings")
		return cls(
			login=settings.api_login,
			secret_key=settings.get_password("api_secret_key", raise_exception=False),
			sandbox_mode=settings.sandbox_mode,
			staging_token=settings.get_password("staging_token", raise_exception=False),
			session=session,
		)

	def __repr__(self) -> str:
		mode = "sandbox" if self.sandbox_mode else "production"
		return f"<QontoClient {mode} login={self.login}>"

	def _auth_headers(self) -> dict[str, str]:
		headers = {
			# Qonto wants the raw "login:secret" pair. This is deliberately not
			# HTTP Basic auth -- do not base64-encode it.
			"Authorization": f"{self.login}:{self._secret_key}",
			"Accept": "application/json",
		}
		if self.sandbox_mode and self._staging_token:
			headers["X-Qonto-Staging-Token"] = self._staging_token
		return headers

	def get_organization(self) -> dict:
		"""GET /v2/organization -- also serves as the connection test."""
		return self._get("/v2/organization")

	def iter_transactions(
		self,
		bank_account_id: str,
		settled_at_from: Any = None,
		status: str = "completed",
	) -> Iterator[dict]:
		"""Yield transactions of one bank account, oldest first.

		Follows meta.next_page until it is null. Never requests a page beyond
		the last one -- Qonto answers those with 422 rather than an empty list.
		"""
		page: int | None = 1
		while page:
			params = {
				"bank_account_id": bank_account_id,
				"status[]": status,
				"sort_by": "settled_at:asc",
				"per_page": PER_PAGE,
				"page": page,
			}
			if settled_at_from:
				params["settled_at_from"] = _format_timestamp(settled_at_from)

			payload = self._get("/v2/transactions", params=params)
			yield from payload.get("transactions") or []
			page = (payload.get("meta") or {}).get("next_page")

	def _get(self, path: str, params: dict | None = None) -> dict:
		url = f"{self.base_url}{path}"

		for attempt in range(1, MAX_ATTEMPTS + 1):
			try:
				response = self.session.get(
					url,
					params=params,
					timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
				)
			except requests.RequestException as exc:
				if attempt == MAX_ATTEMPTS:
					raise QontoApiError(_("Could not reach the Qonto API: {0}").format(exc)) from exc
				self._backoff(attempt, None)
				continue

			if response.status_code < 400:
				return self._parse(response)

			if response.status_code in RETRY_STATUS_CODES and attempt < MAX_ATTEMPTS:
				self._backoff(attempt, response.headers.get("Retry-After"))
				continue

			raise QontoApiError(
				self._error_message(response),
				status_code=response.status_code,
				body=self._safe_body(response),
			)

		# Not reachable: every path above either returns or raises.
		raise QontoApiError(_("Qonto API request failed."))

	@staticmethod
	def _backoff(attempt: int, retry_after: str | None) -> None:
		delay = BACKOFF_SECONDS * (2 ** (attempt - 1))
		if retry_after:
			try:
				delay = max(delay, float(retry_after))
			except (TypeError, ValueError):
				pass
		time.sleep(delay)

	@staticmethod
	def _parse(response: Any) -> dict:
		try:
			return response.json()
		except ValueError as exc:
			raise QontoApiError(
				_("Qonto returned a response that is not JSON."),
				status_code=response.status_code,
			) from exc

	@staticmethod
	def _safe_body(response: Any) -> str:
		return (getattr(response, "text", "") or "")[:MAX_BODY_CHARS]

	@classmethod
	def _error_message(cls, response: Any) -> str:
		status = response.status_code
		if status == 401:
			return _("Qonto rejected the credentials. Check the API login and secret key.")
		if status == 403:
			return _("The Qonto API key is not allowed to read this resource.")
		if status == 404:
			return _("Qonto does not know this resource (404).")
		if status == 422:
			body = cls._safe_body(response)
			if "search_limit_reached" in body:
				return _("Qonto refused the query: too many results. Narrow the date range.")
			return _("Qonto rejected the request parameters (422).")
		return _("The Qonto API returned HTTP {0}.").format(status)
