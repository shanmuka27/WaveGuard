import json

import pytest
import requests

from backend.schemas import Event
from backend.services.watsonx_client import (
    WatsonxClient,
    WatsonxError,
    WatsonxSettings,
    build_granite_input,
    load_prerecorded,
    parse_explanation,
)

EVENT = Event(
    event_id="evt-test",
    classification="seiche_like",
    severity="warning",
    confidence=0.9,
    affected_nodes=["LUDINGTON-01", "MUSKEGON-02", "HOLLAND-03"],
    amplitude_cm=6.0,
    period_seconds=6.0,
    correlation_score=0.95,
)

GRANITE_JSON = {
    "summary": "Three nodes oscillate together.",
    "evidence": ["Amplitude 6.0 cm", "Correlation 0.95"],
    "recommended_actions": ["Clear the piers"],
    "public_warning": "Stay off piers.",
}

SETTINGS = WatsonxSettings(
    api_key="key", project_id="project", url="https://example.test", model_id="ibm/granite-test"
)


class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, chat_response, iam_status=200):
        self.chat_response = chat_response
        self.iam_status = iam_status
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if "iam.cloud.ibm.com" in url:
            return FakeResponse(self.iam_status, {"access_token": "token", "expires_in": 3600})
        if isinstance(self.chat_response, Exception):
            raise self.chat_response
        return self.chat_response


def chat_reply(content):
    return FakeResponse(200, {"choices": [{"message": {"content": content}}]})


def test_parse_explanation_accepts_code_fences_and_surrounding_text():
    text = "Here you go:\n```json\n" + json.dumps(GRANITE_JSON) + "\n```"
    assert parse_explanation(text).summary == GRANITE_JSON["summary"]


def test_parse_explanation_rejects_missing_fields():
    with pytest.raises(WatsonxError) as error:
        parse_explanation(json.dumps({"summary": "Only a summary"}))
    assert error.value.code == "invalid_output"


def test_granite_input_contains_only_event_and_node_labels():
    facts = build_granite_input(EVENT, {"LUDINGTON-01": "physical", "MUSKEGON-02": "simulated"})
    assert set(facts) == {"event", "nodes"}
    assert facts["event"]["severity"] == "warning"
    sources = {node["node_id"]: node["source"] for node in facts["nodes"]}
    assert sources == {
        "LUDINGTON-01": "physical",
        "MUSKEGON-02": "simulated",
        "HOLLAND-03": "unknown",
    }


def test_explain_keeps_detector_severity_and_caches_result():
    session = FakeSession(chat_reply(json.dumps(GRANITE_JSON)))
    client = WatsonxClient(SETTINGS, session=session)

    result = client.explain(EVENT)
    again = client.explain(EVENT)

    assert result.source == "granite"
    assert result.severity == "warning"
    assert result.classification == "seiche_like"
    assert result.explanation.recommended_actions == ["Clear the piers"]
    assert "simulated or unverified" in result.explanation.summary
    assert "Maximum peak-to-trough amplitude" in result.explanation.evidence[1]
    assert "no real shoreline hazard is confirmed" in result.explanation.public_warning
    assert again is result
    chat_calls = [call for call in session.calls if "/ml/v1/text/chat" in call[0]]
    assert len(chat_calls) == 1
    body = chat_calls[0][1]["json"]
    assert body["model_id"] == "ibm/granite-test"
    assert body["project_id"] == "project"
    assert "evt-test" in body["messages"][1]["content"]


def test_explain_without_credentials_raises_not_configured():
    client = WatsonxClient(
        WatsonxSettings(api_key="", project_id="", url="https://example.test", model_id="m"),
        session=FakeSession(chat_reply("{}")),
    )
    with pytest.raises(WatsonxError) as error:
        client.explain(EVENT)
    assert error.value.code == "not_configured"


def test_rejected_credentials_raise_auth_failed():
    client = WatsonxClient(SETTINGS, session=FakeSession(chat_reply("{}"), iam_status=400))
    with pytest.raises(WatsonxError) as error:
        client.explain(EVENT)
    assert error.value.code == "auth_failed"


def test_network_timeout_is_reported():
    client = WatsonxClient(SETTINGS, session=FakeSession(requests.Timeout()))
    with pytest.raises(WatsonxError) as error:
        client.explain(EVENT)
    assert error.value.code == "timeout"
    assert client.status()["last_error"]


def test_prerecorded_example_keeps_its_own_event_identity():
    result = load_prerecorded()
    assert result.source == "prerecorded"
    assert result.event_id == "evt-example01"
    assert result.severity == "warning"
    assert result.explanation.public_warning
