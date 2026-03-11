"""Tests for Gemini LLM client."""

import os
import pytest
from unittest.mock import Mock, patch


class TestGeminiClient:
    """Test suite for GeminiClient."""

    def test_init_without_api_key_raises(self):
        """Should raise error if no API key provided."""
        with patch.dict(os.environ, {}, clear=True):
            from src.llm.gemini_client import GeminiClient
            with pytest.raises(ValueError, match="API key required"):
                GeminiClient(api_key=None)

    def test_init_with_api_key(self):
        """Should initialize with valid API key."""
        with patch("google.genai.Client"):
            from src.llm.gemini_client import GeminiClient
            client = GeminiClient(api_key="test-key")
            assert client.api_key == "test-key"
            assert client.default_model == "gemini-2.5-flash"

    def test_model_selection(self):
        """Should have correct model mappings."""
        with patch("google.genai.Client"):
            from src.llm.gemini_client import GeminiClient
            client = GeminiClient(api_key="test-key")

            assert client.MODELS["fast"] == "gemini-2.5-flash"
            assert client.MODELS["reasoning"] == "gemini-3-pro-preview"
            assert client.MODELS["balanced"] == "gemini-3-flash-preview"
