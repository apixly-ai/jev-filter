import json

import httpx
import pytest

from jev_context.provider import Client, ProviderError
from jev_context.validation import validate_response

BODY = {
    "model": "jev-1.13.0",
    "state": "sample",
    "questions": {
        "q": {"type": "choice", "instructions": "Choose", "criteria": {"yes": "Yes", "no": "No"}}
    },
}
ANSWER = {
    "model": "jev-1.13.0",
    "answers": {
        "q": {
            "type": "choice",
            "choice": "yes",
            "confidence": 1.0,
            "probabilities": {"yes": 1.0, "no": 0.0},
        }
    },
    "usage": {"input_tokens": 10, "output_tokens": 2},
}


def test_reuses_client_and_never_redirects():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json=ANSWER)

    with Client(api_key="test-key", transport=httpx.MockTransport(handler)) as client:
        client.call(BODY)
        client.call(BODY)
        assert client.stats["clients_created"] == 1
        assert client.stats["client_reuses"] == 1
    assert all(r.url.host == "api.typesafe.ai" for r in seen)
    assert all(r.headers["authorization"] == "Bearer test-key" for r in seen)


def test_retry_marks_unknown_prior_usage():
    responses = iter(
        [httpx.Response(429, headers={"retry-after": "0"}), httpx.Response(200, json=ANSWER)]
    )
    with Client(
        api_key="test-key",
        transport=httpx.MockTransport(lambda _: next(responses)),
        sleep=lambda _: None,
    ) as client:
        result = client.call(BODY)
        assert result["attempts"] == 2 and not result["usage_complete"]
        assert client.stats["requests"] == 2


def test_transport_failure_not_retried_or_leaked():
    def failure(request):
        raise httpx.ConnectError("PRIVATE_BODY", request=request)

    with Client(api_key="test-key", transport=httpx.MockTransport(failure)) as client:
        with pytest.raises(ProviderError) as caught:
            client.call(BODY)
        assert "PRIVATE_BODY" not in str(caught.value)
        assert client.stats["requests"] == 1


def test_redirect_and_invalid_body_are_safe_errors():
    for response in [
        httpx.Response(302, headers={"location": "https://example.invalid"}),
        httpx.Response(200, text="PRIVATE_BODY"),
    ]:
        with Client(
            api_key="test-key", transport=httpx.MockTransport(lambda _: response)
        ) as client:
            with pytest.raises(ProviderError) as caught:
                client.call(BODY)
            assert "PRIVATE_BODY" not in str(caught.value)
            assert client.stats["requests"] == 1


def test_invalid_distribution_rejected():
    bad = json.loads(json.dumps(ANSWER))
    bad["answers"]["q"]["probabilities"] = {"yes": 1, "no": 1}
    with pytest.raises(ValueError):
        validate_response(BODY, bad)


def test_failed_retries_preserve_every_unknown_physical_attempt():
    with Client(
        api_key="test-key",
        transport=httpx.MockTransport(lambda _: httpx.Response(503, headers={"retry-after": "0"})),
        sleep=lambda _: None,
    ) as client:
        with pytest.raises(ProviderError) as caught:
            client.call(BODY)
        assert caught.value.code == "http_503_body_suppressed"
        assert caught.value.unknown_usage_attempts == client.stats["requests"] == 3


def test_invalid_response_after_retry_keeps_unknown_attempt_count():
    responses = iter(
        [
            httpx.Response(429, headers={"retry-after": "0"}),
            httpx.Response(200, text="PRIVATE_BODY"),
        ]
    )
    with Client(
        api_key="test-key",
        transport=httpx.MockTransport(lambda _: next(responses)),
        sleep=lambda _: None,
    ) as client:
        with pytest.raises(ProviderError) as caught:
            client.call(BODY)
        assert caught.value.unknown_usage_attempts == 2
        assert "PRIVATE_BODY" not in str(caught.value)
