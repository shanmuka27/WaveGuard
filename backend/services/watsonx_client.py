"""IBM watsonx.ai Granite client that explains detector events.

Granite only explains a finalized event. Severity and classification always come
from the deterministic detector and are never taken from the model response.
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

import requests
from dotenv import load_dotenv
from pydantic import BaseModel, Field, ValidationError, field_validator

from backend.schemas import Event

load_dotenv()

IBM_DIR = Path(__file__).resolve().parents[2] / "ibm"
PROMPT_PATH = IBM_DIR / "warning_prompt.md"
EXAMPLE_PATH = IBM_DIR / "example_event.json"

IAM_URL = "https://iam.cloud.ibm.com/identity/token"
CHAT_API_VERSION = "2024-10-08"

NODE_LOCATIONS = {
    "LUDINGTON-01": "Ludington",
    "MUSKEGON-02": "Muskegon",
    "HOLLAND-03": "Holland",
}


class Explanation(BaseModel):
    summary: str = Field(min_length=1)
    evidence: list[str] = Field(min_length=1, max_length=8)
    recommended_actions: list[str] = Field(min_length=1, max_length=8)
    public_warning: str = Field(min_length=1)

    @field_validator("evidence", "recommended_actions")
    @classmethod
    def _drop_blank_items(cls, items: list[str]) -> list[str]:
        cleaned = [item.strip() for item in items if item and item.strip()]
        if not cleaned:
            raise ValueError("must contain at least one non-empty item")
        return cleaned


class ExplanationResult(BaseModel):
    event_id: str
    severity: str
    classification: str
    source: str  # "granite" or "prerecorded"
    model_id: Optional[str] = None
    generated_at: datetime
    explanation: Explanation


class WatsonxError(Exception):
    """Raised when Granite cannot produce a usable explanation."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class WatsonxSettings:
    api_key: str
    project_id: str
    url: str
    model_id: str
    timeout_seconds: float = 30.0

    @classmethod
    def from_env(cls) -> "WatsonxSettings":
        return cls(
            api_key=os.getenv("WATSONX_API_KEY", "").strip(),
            project_id=os.getenv("WATSONX_PROJECT_ID", "").strip(),
            url=os.getenv("WATSONX_URL", "https://us-south.ml.cloud.ibm.com").strip().rstrip("/"),
            model_id=os.getenv("WATSONX_MODEL_ID", "ibm/granite-4-h-small").strip(),
            timeout_seconds=float(os.getenv("WATSONX_TIMEOUT_SECONDS", "30")),
        )

    @property
    def configured(self) -> bool:
        return bool(self.api_key and self.project_id and self.url and self.model_id)


def build_granite_input(event: Event, node_sources: Optional[dict[str, str]] = None) -> dict:
    """Return the only facts Granite is allowed to use."""
    node_sources = node_sources or {}
    nodes = [
        {
            "node_id": node_id,
            "location": NODE_LOCATIONS.get(node_id, "unknown"),
            "source": node_sources.get(node_id, "unknown"),
        }
        for node_id in event.affected_nodes
    ]
    return {"event": event.model_dump(mode="json"), "nodes": nodes}


def parse_explanation(text: str) -> Explanation:
    """Extract and validate the JSON object returned by Granite."""
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.IGNORECASE)
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end <= start:
        raise WatsonxError("invalid_output", "Granite did not return a JSON object")
    try:
        payload = json.loads(cleaned[start : end + 1])
        return Explanation.model_validate(payload)
    except (json.JSONDecodeError, ValidationError) as error:
        raise WatsonxError(
            "invalid_output", f"Granite returned JSON in an unexpected shape: {error}"
        ) from error


def load_prerecorded(event: Optional[Event] = None) -> ExplanationResult:
    """Return the saved example response, clearly labeled as prerecorded."""
    example = json.loads(EXAMPLE_PATH.read_text(encoding="utf-8"))
    example_event = example["input"]["event"]
    return ExplanationResult(
        event_id=event.event_id if event else example_event["event_id"],
        severity=event.severity.value if event else example_event["severity"],
        classification=event.classification.value if event else example_event["classification"],
        source="prerecorded",
        model_id=None,
        generated_at=datetime.now(timezone.utc),
        explanation=Explanation.model_validate(example["response"]),
    )


class WatsonxClient:
    def __init__(
        self,
        settings: Optional[WatsonxSettings] = None,
        session: Optional[requests.Session] = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.settings = settings or WatsonxSettings.from_env()
        self.session = session or requests.Session()
        self._clock = clock
        self._token: Optional[str] = None
        self._token_expires_at = 0.0
        self._cache: dict[str, ExplanationResult] = {}
        self.last_error: Optional[str] = None

    @property
    def configured(self) -> bool:
        return self.settings.configured

    def status(self) -> dict:
        return {
            "configured": self.configured,
            "model_id": self.settings.model_id,
            "last_error": self.last_error,
        }

    def explain(
        self,
        event: Event,
        node_sources: Optional[dict[str, str]] = None,
        refresh: bool = False,
    ) -> ExplanationResult:
        if not refresh and event.event_id in self._cache:
            return self._cache[event.event_id]
        if not self.configured:
            raise WatsonxError(
                "not_configured",
                "Set WATSONX_API_KEY and WATSONX_PROJECT_ID in .env to enable Granite.",
            )

        facts = build_granite_input(event, node_sources)
        messages = [
            {"role": "system", "content": PROMPT_PATH.read_text(encoding="utf-8")},
            {
                "role": "user",
                "content": "Explain this WaveGuard event using only these facts:\n"
                + json.dumps(facts, indent=2),
            },
        ]
        try:
            explanation = parse_explanation(self._chat(messages))
        except WatsonxError as error:
            self.last_error = error.message
            raise

        result = ExplanationResult(
            event_id=event.event_id,
            severity=event.severity.value,
            classification=event.classification.value,
            source="granite",
            model_id=self.settings.model_id,
            generated_at=datetime.now(timezone.utc),
            explanation=explanation,
        )
        self._cache[event.event_id] = result
        self.last_error = None
        return result

    def _chat(self, messages: list[dict]) -> str:
        response = self._post(
            f"{self.settings.url}/ml/v1/text/chat",
            params={"version": CHAT_API_VERSION},
            headers={"Authorization": f"Bearer {self._access_token()}"},
            json={
                "model_id": self.settings.model_id,
                "project_id": self.settings.project_id,
                "messages": messages,
                "max_tokens": 700,
                "temperature": 0,
            },
        )
        try:
            return response.json()["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as error:
            raise WatsonxError(
                "invalid_output", "watsonx.ai returned an unexpected response body"
            ) from error

    def _access_token(self) -> str:
        if self._token and self._clock() < self._token_expires_at - 60:
            return self._token
        response = self._post(
            IAM_URL,
            data={
                "grant_type": "urn:ibm:params:oauth:grant-type:apikey",
                "apikey": self.settings.api_key,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            auth_step=True,
        )
        payload = response.json()
        self._token = payload["access_token"]
        self._token_expires_at = float(
            payload.get("expiration", self._clock() + payload.get("expires_in", 3600))
        )
        return self._token

    def _post(self, url: str, auth_step: bool = False, **kwargs) -> requests.Response:
        try:
            response = self.session.post(url, timeout=self.settings.timeout_seconds, **kwargs)
        except requests.Timeout as error:
            self.last_error = "IBM watsonx.ai timed out"
            raise WatsonxError("timeout", self.last_error) from error
        except requests.RequestException as error:
            self.last_error = f"Could not reach IBM Cloud: {error.__class__.__name__}"
            raise WatsonxError("unreachable", self.last_error) from error

        if response.status_code in (401, 403) or (auth_step and response.status_code >= 400):
            self._token = None
            self.last_error = f"IBM Cloud rejected the credentials (HTTP {response.status_code})"
            raise WatsonxError("auth_failed", self.last_error)
        if response.status_code >= 400:
            self.last_error = f"watsonx.ai request failed (HTTP {response.status_code})"
            raise WatsonxError("request_failed", self.last_error)
        return response


_client: Optional[WatsonxClient] = None


def get_client() -> WatsonxClient:
    global _client
    if _client is None:
        _client = WatsonxClient()
    return _client
