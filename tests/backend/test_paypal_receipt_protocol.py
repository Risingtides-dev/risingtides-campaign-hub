"""Protocol controls use fake HTTP only, with no credentials or provider calls."""
from copy import deepcopy

import pytest

from campaign_manager.services.paypal_payouts import PayPalConfig, PayPalError, PayPalPayouts
from tests.backend.test_payout_reconciliation import ADMIN, _approve, _draft, provider  # noqa: F401


class Response:
    def __init__(self, body, status=200):
        self.body, self.status_code = body, status

    def json(self):
        if isinstance(self.body, Exception):
            raise self.body
        return deepcopy(self.body)


class FakeHttp:
    def __init__(self):
        self.auth_status = 401
        self.auth_posts = []
        self.funds_posts = []
        self.gets = []
        self.pages = []

    def post(self, url, **kwargs):
        self.auth_posts.append(url)
        return Response({"access_token": "synthetic-token"}, self.auth_status)

    def request(self, method, url, **kwargs):
        if method == "POST":
            self.funds_posts.append(kwargs["json"])
            sender = kwargs["json"]["sender_batch_header"]
            return Response({"batch_header": {"payout_batch_id": "PB-AUTH", "batch_status": "PENDING",
                                               "sender_batch_header": sender}})
        self.gets.append((url, kwargs["params"]["page"]))
        return self.pages[kwargs["params"]["page"] - 1]


def _client(http):
    return PayPalPayouts(PayPalConfig("synthetic-id", "synthetic-secret", "live"), session=http)


def test_oauth_failure_leaves_draft_without_a_funds_post_and_can_be_corrected(app, client, provider):
    http = FakeHttp()
    real_client = _client(http)
    app.config["PAYPAL_CLIENT_FACTORY"] = lambda: real_client
    draft = _draft(client)
    response = _approve(client, draft["id"])
    assert response.status_code == 502
    assert http.funds_posts == []
    stored = client.get("/api/payouts/admin/batches", headers=ADMIN).json["batches"][0]
    assert stored["status"] == "draft"
    assert stored["approved_at"] == ""
    http.auth_status = 200
    assert _approve(client, draft["id"]).status_code == 200
    assert len(http.funds_posts) == 1
    assert len(http.auth_posts) == 2  # successful preflight token is reused for funds POST
    assert _approve(client, draft["id"]).status_code == 400
    assert len(http.funds_posts) == 1


@pytest.mark.parametrize("identifier", ["../other", "PB-1?other=true", "https://other.test/x", "x" * 65, None])
def test_client_rejects_unsafe_provider_path_id_before_authentication(identifier):
    http = FakeHttp()
    with pytest.raises(PayPalError):
        _client(http).get_batch(identifier)
    assert http.auth_posts == []
    assert http.gets == []


@pytest.mark.parametrize("body", [[], None, ValueError("synthetic malformed JSON")])
def test_client_never_treats_malformed_provider_json_as_an_empty_success(body):
    http = FakeHttp()
    http.auth_status = 200
    http.pages = [Response(body)]
    with pytest.raises(PayPalError):
        _client(http).get_batch("PB-1")


@pytest.mark.parametrize("pages", [0, 51, "bad", True])
def test_client_rejects_unbounded_or_invalid_pagination(pages):
    http = FakeHttp()
    http.auth_status = 200
    http.pages = [Response({"items": [], "total_pages": pages})]
    with pytest.raises(PayPalError):
        _client(http).get_batch("PB-1")
    assert len(http.gets) == 1


def test_client_refuses_missing_later_page_instead_of_returning_partial_receipt():
    http = FakeHttp()
    http.auth_status = 200
    http.pages = [Response({"items": [], "total_pages": 2}), Response({"items": None})]
    with pytest.raises(PayPalError):
        _client(http).get_batch("PB-1")


@pytest.mark.parametrize("total", [2, True, "1", -1])
def test_client_checks_reported_total_against_collected_items(total):
    http = FakeHttp()
    http.auth_status = 200
    http.pages = [Response({"items": [{"payout_item_id": "PI-1"}], "total_pages": 1, "total_items": total})]
    with pytest.raises(PayPalError):
        _client(http).get_batch("PB-1")
