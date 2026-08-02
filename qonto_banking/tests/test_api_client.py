import json
from unittest.mock import patch

import requests

from qonto_banking.api.client import (
	PRODUCTION_BASE_URL,
	SANDBOX_BASE_URL,
	QontoApiError,
	QontoClient,
)
from qonto_banking.tests.compat import BaseTestCase

LOGIN = "test-org-1234"
SECRET = "never-log-me-0000"


class FakeResponse:
	def __init__(self, status_code=200, payload=None, text=None, headers=None):
		self.status_code = status_code
		self._payload = payload
		self.headers = headers or {}
		if text is not None:
			self.text = text
		else:
			self.text = json.dumps(payload) if payload is not None else ""

	def json(self):
		if self._payload is None:
			raise ValueError("not json")
		return self._payload


class FakeSession:
	"""Stands in for requests.Session and records what was asked of it."""

	def __init__(self, *responses):
		self.headers = {}
		self._responses = list(responses)
		self.calls = []

	def get(self, url, params=None, timeout=None):
		self.calls.append({"url": url, "params": params, "timeout": timeout})
		result = self._responses.pop(0)
		if isinstance(result, Exception):
			raise result
		return result


def make_client(session, sandbox_mode=False, staging_token=None):
	return QontoClient(
		login=LOGIN,
		secret_key=SECRET,
		sandbox_mode=sandbox_mode,
		staging_token=staging_token,
		session=session,
	)


class TestQontoClientAuth(BaseTestCase):
	def test_authorization_header_is_the_raw_pair(self):
		"""Qonto wants login:secret verbatim - base64 would be rejected."""
		session = FakeSession()
		make_client(session)
		self.assertEqual(session.headers["Authorization"], f"{LOGIN}:{SECRET}")

	def test_production_base_url(self):
		client = make_client(FakeSession())
		self.assertEqual(client.base_url, PRODUCTION_BASE_URL)

	def test_sandbox_sets_base_url_and_staging_header(self):
		session = FakeSession()
		client = make_client(session, sandbox_mode=True, staging_token="stg-1")
		self.assertEqual(client.base_url, SANDBOX_BASE_URL)
		self.assertEqual(session.headers["X-Qonto-Staging-Token"], "stg-1")

	def test_no_staging_header_in_production(self):
		session = FakeSession()
		make_client(session, sandbox_mode=False, staging_token="stg-1")
		self.assertNotIn("X-Qonto-Staging-Token", session.headers)

	def test_repr_does_not_leak_the_secret(self):
		client = make_client(FakeSession())
		self.assertNotIn(SECRET, repr(client))


class TestQontoClientRequests(BaseTestCase):
	def test_get_organization(self):
		payload = {"organization": {"slug": "acme", "bank_accounts": [{"id": "abc"}]}}
		session = FakeSession(FakeResponse(payload=payload))
		result = make_client(session).get_organization()

		self.assertEqual(result, payload)
		self.assertEqual(session.calls[0]["url"], f"{PRODUCTION_BASE_URL}/v2/organization")

	def test_timeouts_are_applied(self):
		session = FakeSession(FakeResponse(payload={}))
		make_client(session).get_organization()
		self.assertEqual(session.calls[0]["timeout"], (10, 30))

	def test_transaction_query_parameters(self):
		session = FakeSession(FakeResponse(payload={"transactions": [], "meta": {"next_page": None}}))
		list(make_client(session).iter_transactions("acc-1", settled_at_from="2026-01-01T00:00:00.000Z"))

		params = session.calls[0]["params"]
		self.assertEqual(params["bank_account_id"], "acc-1")
		self.assertEqual(params["status[]"], "completed")
		self.assertEqual(params["sort_by"], "settled_at:asc")
		self.assertEqual(params["per_page"], 100)
		self.assertEqual(params["settled_at_from"], "2026-01-01T00:00:00.000Z")

	def test_settled_at_from_is_omitted_when_not_given(self):
		session = FakeSession(FakeResponse(payload={"transactions": [], "meta": {"next_page": None}}))
		list(make_client(session).iter_transactions("acc-1"))
		self.assertNotIn("settled_at_from", session.calls[0]["params"])

	def test_pagination_follows_next_page_and_stops(self):
		"""Requesting a page past the last one answers 422, so we must stop exactly."""
		session = FakeSession(
			FakeResponse(payload={"transactions": [{"id": "t1"}], "meta": {"next_page": 2}}),
			FakeResponse(payload={"transactions": [{"id": "t2"}], "meta": {"next_page": None}}),
		)
		transactions = list(make_client(session).iter_transactions("acc-1"))

		self.assertEqual([t["id"] for t in transactions], ["t1", "t2"])
		self.assertEqual(len(session.calls), 2)
		self.assertEqual(session.calls[0]["params"]["page"], 1)
		self.assertEqual(session.calls[1]["params"]["page"], 2)

	def test_missing_transactions_key_is_tolerated(self):
		session = FakeSession(FakeResponse(payload={"meta": {"next_page": None}}))
		self.assertEqual(list(make_client(session).iter_transactions("acc-1")), [])


class TestQontoClientErrors(BaseTestCase):
	def test_retries_on_429_then_succeeds(self):
		session = FakeSession(
			FakeResponse(status_code=429, headers={"Retry-After": "0"}),
			FakeResponse(payload={"organization": {}}),
		)
		with patch("qonto_banking.api.client.time.sleep") as sleep:
			result = make_client(session).get_organization()

		self.assertEqual(result, {"organization": {}})
		self.assertEqual(len(session.calls), 2)
		sleep.assert_called_once()

	def test_gives_up_after_three_attempts_on_5xx(self):
		session = FakeSession(*[FakeResponse(status_code=503) for _ in range(3)])
		with patch("qonto_banking.api.client.time.sleep"):
			with self.assertRaises(QontoApiError) as ctx:
				make_client(session).get_organization()

		self.assertEqual(ctx.exception.status_code, 503)
		self.assertEqual(len(session.calls), 3)

	def test_401_fails_immediately_with_a_usable_hint(self):
		session = FakeSession(FakeResponse(status_code=401, text="unauthorized"))
		with self.assertRaises(QontoApiError) as ctx:
			make_client(session).get_organization()

		self.assertEqual(ctx.exception.status_code, 401)
		self.assertIn("login", str(ctx.exception).lower())
		self.assertEqual(len(session.calls), 1, "authentication failures must not be retried")

	def test_422_search_limit_reached(self):
		session = FakeSession(
			FakeResponse(status_code=422, text='{"errors":[{"code":"search_limit_reached"}]}')
		)
		with self.assertRaises(QontoApiError) as ctx:
			list(make_client(session).iter_transactions("acc-1"))

		self.assertEqual(ctx.exception.status_code, 422)
		self.assertIn("too many results", str(ctx.exception))

	def test_connection_error_is_wrapped_and_retried(self):
		session = FakeSession(
			requests.ConnectionError("boom"),
			requests.ConnectionError("boom"),
			requests.ConnectionError("boom"),
		)
		with patch("qonto_banking.api.client.time.sleep"):
			with self.assertRaises(QontoApiError):
				make_client(session).get_organization()

		self.assertEqual(len(session.calls), 3)

	def test_non_json_response_is_wrapped(self):
		session = FakeSession(FakeResponse(status_code=200, text="<html>nope</html>"))
		with self.assertRaises(QontoApiError) as ctx:
			make_client(session).get_organization()
		self.assertIn("not JSON", str(ctx.exception))

	def test_secret_never_appears_in_errors(self):
		session = FakeSession(FakeResponse(status_code=401, text=f"denied for {LOGIN}"))
		with self.assertRaises(QontoApiError) as ctx:
			make_client(session).get_organization()

		self.assertNotIn(SECRET, str(ctx.exception))
		self.assertNotIn(SECRET, ctx.exception.body or "")

	def test_error_body_is_truncated(self):
		# 500 is retryable, so all three attempts need a response.
		session = FakeSession(*[FakeResponse(status_code=500, text="x" * 5000) for _ in range(3)])
		with patch("qonto_banking.api.client.time.sleep"):
			with self.assertRaises(QontoApiError) as ctx:
				make_client(session).get_organization()

		self.assertEqual(len(ctx.exception.body), 1000)
