"""
llm.py — IBM Granite (watsonx.ai) API Client
=============================================
Wraps the IBM watsonx.ai Inference API so every other module
just calls `granite.generate(prompt)` and gets a string back.

Architecture:
  - GraniteClient  : thin HTTP wrapper around the REST API
  - A module-level singleton `granite` is imported everywhere

Authentication flow:
  IBM watsonx.ai uses IAM token-based auth.
  We exchange the API key for a short-lived bearer token, cache it,
  and refresh it before it expires (tokens live 60 minutes).

Why httpx and not the ibm-watson SDK?
  The official SDK bundles many dependencies and doesn't yet expose
  the newest Granite models cleanly. Using httpx directly gives us
  full control over timeouts, retries, and error messages, which is
  critical for a chat app where latency matters.

Model used: ibm/granite-13b-chat-v2
  - Best balance of reasoning quality and speed for text-to-SQL
  - Supports structured instruction following
  - Context window: 8192 tokens
"""

import logging
import time
from typing import Optional

import httpx

from config import settings

logger = logging.getLogger(__name__)


# ── IAM Token Manager ────────────────────────────────────────────────────────

class IAMTokenManager:
    """
    Manages IBM IAM bearer tokens.

    Tokens expire after 3600 seconds. We refresh 5 minutes early
    to avoid races where a token expires mid-request.
    """

    IAM_URL = "https://iam.cloud.ibm.com/identity/token"
    REFRESH_BUFFER_SECONDS = 300   # refresh 5 min before expiry

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key
        self._token: Optional[str] = None
        self._expires_at: float = 0.0

    def get_token(self) -> str:
        """Return a valid token, refreshing if necessary."""
        if self._is_expired():
            self._refresh()
        return self._token

    def _is_expired(self) -> bool:
        return time.time() >= (self._expires_at - self.REFRESH_BUFFER_SECONDS)

    def _refresh(self) -> None:
        """Exchange API key for a fresh IAM bearer token."""
        logger.debug("Refreshing IBM IAM token...")
        try:
            resp = httpx.post(
                self.IAM_URL,
                data={
                    "grant_type": "urn:ibm:params:oauth:grant-type:apikey",
                    "apikey": self._api_key,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=15,
            )
            resp.raise_for_status()
            payload = resp.json()
            self._token = payload["access_token"]
            self._expires_at = time.time() + int(payload.get("expires_in", 3600))
            logger.debug("IAM token refreshed successfully.")
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(
                f"IBM IAM token refresh failed ({exc.response.status_code}): "
                f"{exc.response.text}"
            ) from exc
        except Exception as exc:
            raise RuntimeError(f"IBM IAM token refresh error: {exc}") from exc


# ── Granite Client ───────────────────────────────────────────────────────────

class GraniteClient:
    """
    IBM watsonx.ai text generation client for Granite models.

    Exposes a single `generate(prompt, **kwargs)` method that handles
    auth, request building, response parsing, and error handling.

    Generation parameters (can be overridden per-call):
      max_new_tokens : hard cap on output length
      temperature    : 0.0 = deterministic (best for SQL generation)
      top_p          : nucleus sampling threshold
      repetition_penalty : discourages the model from repeating itself
    """

    INFERENCE_PATH = "/ml/v1/text/generation?version=2023-05-29"

    # Default generation parameters tuned for Granite 3 SQL generation
    DEFAULT_PARAMS = {
        "max_new_tokens": 800,
        "temperature": 0.0,       # deterministic — same input → same SQL
        "top_p": 1.0,
        "repetition_penalty": 1.05,
        "stop_sequences": ["<|user|>", "<|system|>", "\n\nUser:", "\n\nHuman:"],
    }

    def __init__(self) -> None:
        self._iam = IAMTokenManager(settings.watsonx_api_key)
        self._base_url = settings.watsonx_url
        self._project_id = settings.watsonx_project_id
        self._model_id = settings.granite_model_id
        # Persistent HTTP client (connection pooling, keep-alive)
        self._client = httpx.Client(timeout=60)

    def generate(
        self,
        prompt: str,
        max_new_tokens: int = 800,
        temperature: float = 0.0,
    ) -> str:
        """
        Send a prompt to IBM Granite and return the generated text.

        Args:
            prompt:         The complete formatted prompt string.
            max_new_tokens: Maximum tokens to generate.
            temperature:    Sampling temperature (0 = deterministic).

        Returns:
            The generated text string (SQL + explanation from the model).

        Raises:
            RuntimeError: On API failure, with a human-readable message.
        """
        url = self._base_url + self.INFERENCE_PATH
        token = self._iam.get_token()

        params = {**self.DEFAULT_PARAMS, "max_new_tokens": max_new_tokens, "temperature": temperature}

        payload = {
            "model_id": self._model_id,
            "project_id": self._project_id,
            "input": prompt,
            "parameters": params,
        }

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        try:
            logger.debug(f"Calling Granite model: {self._model_id}")
            resp = self._client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            error_body = exc.response.text[:500]
            raise RuntimeError(
                f"Granite API error ({exc.response.status_code}): {error_body}"
            ) from exc
        except httpx.TimeoutException:
            raise RuntimeError(
                "Granite API request timed out. The model may be under heavy load."
            )
        except Exception as exc:
            raise RuntimeError(f"Granite API unexpected error: {exc}") from exc

        data = resp.json()

        # Extract generated text from the response envelope
        try:
            results = data.get("results", [])
            if not results:
                raise ValueError("No results in Granite response")
            generated_text = results[0].get("generated_text", "").strip()
            if not generated_text:
                raise ValueError("Empty generated_text in Granite response")
            return generated_text
        except (KeyError, IndexError, ValueError) as exc:
            raise RuntimeError(
                f"Unexpected Granite response shape: {exc}\nRaw: {str(data)[:300]}"
            ) from exc

    def close(self) -> None:
        """Close the underlying HTTP client. Called at app shutdown."""
        self._client.close()


# ── Module-level singleton ───────────────────────────────────────────────────
granite = GraniteClient()
