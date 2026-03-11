"""
Gemini LLM Client for ClaimFlow AI.

Uses the new unified Google GenAI SDK (google-genai).
Supports Gemini 3 Pro, Gemini 3 Flash, Gemini 2.5 Flash/Pro models.
"""

import os
from typing import Generator

from google import genai
from google.genai import types

from ..utils.logger import get_logger

logger = get_logger("claimflow.llm")


class GeminiClient:
    """
    Unified Gemini client for ClaimFlow AI.

    Handles text generation, chat conversations, and embeddings.
    """

    # Available models as of 2026
    MODELS = {
        "fast": "gemini-2.5-flash",           # Cost-effective, high-volume
        "balanced": "gemini-3-flash-preview",  # Balanced speed/intelligence
        "reasoning": "gemini-3-pro-preview",   # Complex agentic workflows
        "pro": "gemini-2.5-pro",               # Advanced reasoning
    }

    def __init__(
        self,
        api_key: str | None = None,
        default_model: str = "gemini-2.5-flash",
        temperature: float = 0.3,
        max_output_tokens: int = 8192,
    ):
        """
        Initialize Gemini client.

        Args:
            api_key: Gemini API key. Falls back to GEMINI_API_KEY env var.
            default_model: Default model to use for generation.
            temperature: Generation temperature (0.0-1.0).
            max_output_tokens: Maximum tokens in response.
        """
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        if not self.api_key:
            raise ValueError(
                "Gemini API key required. Set GEMINI_API_KEY env var or pass api_key."
            )

        self.default_model = default_model
        self.temperature = temperature
        self.max_output_tokens = max_output_tokens

        # Initialize the client
        self._client = genai.Client(api_key=self.api_key)
        self._chat_sessions: dict[str, genai.ChatSession] = {}

        logger.info(f"Gemini client initialized with model: {default_model}")

    def generate(
        self,
        prompt: str,
        system_instruction: str | None = None,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        """
        Generate text response from Gemini.

        Args:
            prompt: User prompt/query.
            system_instruction: Optional system instruction.
            model: Model override (uses default if not specified).
            temperature: Temperature override.
            max_tokens: Max tokens override.

        Returns:
            Generated text response.
        """
        model = model or self.default_model
        temp = temperature if temperature is not None else self.temperature
        max_out = max_tokens or self.max_output_tokens

        config = types.GenerateContentConfig(
            temperature=temp,
            max_output_tokens=max_out,
            system_instruction=system_instruction,
        )

        try:
            response = self._client.models.generate_content(
                model=model,
                contents=prompt,
                config=config,
            )
            return response.text
        except Exception as e:
            logger.error(f"Generation failed: {e}")
            raise

    def generate_stream(
        self,
        prompt: str,
        system_instruction: str | None = None,
        model: str | None = None,
    ) -> Generator[str, None, None]:
        """
        Stream text response from Gemini.

        Args:
            prompt: User prompt/query.
            system_instruction: Optional system instruction.
            model: Model override.

        Yields:
            Text chunks as they're generated.
        """
        model = model or self.default_model

        config = types.GenerateContentConfig(
            temperature=self.temperature,
            max_output_tokens=self.max_output_tokens,
            system_instruction=system_instruction,
        )

        try:
            for chunk in self._client.models.generate_content_stream(
                model=model,
                contents=prompt,
                config=config,
            ):
                if chunk.text:
                    yield chunk.text
        except Exception as e:
            logger.error(f"Streaming generation failed: {e}")
            raise

    def chat(
        self,
        session_id: str,
        message: str,
        model: str | None = None,
    ) -> str:
        """
        Send a message in a chat session.

        Args:
            session_id: Unique identifier for the chat session.
            message: User message.
            model: Model override.

        Returns:
            Assistant response.
        """
        model = model or self.default_model

        # Create new session if doesn't exist
        if session_id not in self._chat_sessions:
            self._chat_sessions[session_id] = self._client.chats.create(
                model=model
            )
            logger.debug(f"Created new chat session: {session_id}")

        session = self._chat_sessions[session_id]

        try:
            response = session.send_message(message)
            return response.text
        except Exception as e:
            logger.error(f"Chat message failed: {e}")
            raise

    def clear_chat(self, session_id: str) -> None:
        """Clear a chat session."""
        if session_id in self._chat_sessions:
            del self._chat_sessions[session_id]
            logger.debug(f"Cleared chat session: {session_id}")

    def embed(
        self,
        text: str | list[str],
        model: str = "models/text-embedding-004",
    ) -> list[list[float]]:
        """
        Generate embeddings for text.

        Args:
            text: Single text or list of texts to embed.
            model: Embedding model to use.

        Returns:
            List of embedding vectors.
        """
        if isinstance(text, str):
            text = [text]

        try:
            result = self._client.models.embed_content(
                model=model,
                contents=text,
            )
            return [embedding.values for embedding in result.embeddings]
        except Exception as e:
            logger.error(f"Embedding failed: {e}")
            raise

    def analyze_rejection(self, rejection_email: str, case_context: str) -> dict:
        """
        Analyze a claim rejection email.

        Args:
            rejection_email: Raw rejection email text.
            case_context: JSON string of case details.

        Returns:
            Structured analysis of the rejection.
        """
        system_prompt = """You are an insurance claim analyst. Analyze rejection emails
and extract structured information. Be precise and factual."""

        prompt = f"""Analyze this insurance claim rejection email and extract:

1. rejection_type: The category (non_disclosure, pre_existing, documentation, policy_exclusion, other)
2. stated_reason: The exact reason given by insurer
3. conditions_cited: Any medical conditions mentioned
4. clauses_cited: Policy clauses or terms referenced
5. documents_requested: Any additional documents asked for
6. causality_established: Did insurer prove causal link? (true/false)
7. weak_points: Legal/logical weaknesses in the rejection

CASE CONTEXT:
{case_context}

REJECTION EMAIL:
{rejection_email}

Respond in JSON format only."""

        response = self.generate(
            prompt=prompt,
            system_instruction=system_prompt,
            model=self.MODELS["reasoning"],  # Use reasoning model for analysis
            temperature=0.1,  # Low temperature for structured output
        )

        # Parse JSON response
        import json
        try:
            # Clean response if wrapped in markdown
            cleaned = response.strip()
            if cleaned.startswith("```json"):
                cleaned = cleaned[7:]
            if cleaned.startswith("```"):
                cleaned = cleaned[3:]
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3]
            return json.loads(cleaned.strip())
        except json.JSONDecodeError:
            logger.warning("Failed to parse JSON response, returning raw text")
            return {"raw_response": response}

    def draft_escalation(
        self,
        case_data: dict,
        rejection_analysis: dict,
        precedents: list[dict],
        escalation_level: int = 1,
    ) -> str:
        """
        Draft an escalation email using case data and precedents.

        Args:
            case_data: Case details dictionary.
            rejection_analysis: Parsed rejection analysis.
            precedents: List of relevant precedent cases.
            escalation_level: Current escalation level (1, 2, 3...).

        Returns:
            Drafted escalation email.
        """
        system_prompt = """You are a professional insurance claim advocate.
Draft clear, firm, but professional escalation emails.
Cite precedents and regulations precisely.
Avoid emotional language. Focus on facts and legal grounds."""

        precedent_text = "\n".join([
            f"- {p.get('title', 'Precedent')}: {p.get('key_ruling', p.get('summary', ''))}"
            for p in precedents[:3]
        ])

        prompt = f"""Draft an escalation email for this insurance claim rejection.

ESCALATION LEVEL: {escalation_level} (1=first escalation, 2=senior review request, 3=pre-legal notice)

CASE DETAILS:
- Claimant: {case_data.get('claimant', {}).get('name', 'N/A')}
- Policy: {case_data.get('claimant', {}).get('policy_number', 'N/A')}
- Insurer: {case_data.get('claimant', {}).get('insurer', 'N/A')}
- Claim Condition: {case_data.get('claim', {}).get('condition', 'N/A')}

REJECTION ANALYSIS:
- Rejection Type: {rejection_analysis.get('rejection_type', 'N/A')}
- Stated Reason: {rejection_analysis.get('stated_reason', 'N/A')}
- Weak Points: {rejection_analysis.get('weak_points', 'N/A')}

RELEVANT PRECEDENTS:
{precedent_text}

REQUIREMENTS:
1. Reference claim number and previous correspondence
2. State facts clearly without medical debate
3. Cite the precedents showing similar rejections were overturned
4. Request specific action (medical board review, compliance review, etc.)
5. Set a reasonable response timeline
6. Maintain professional tone throughout

Draft the complete email:"""

        return self.generate(
            prompt=prompt,
            system_instruction=system_prompt,
            model=self.MODELS["balanced"],
            temperature=0.4,
        )

    def close(self) -> None:
        """Close the client and release resources."""
        self._client.close()
        self._chat_sessions.clear()
        logger.info("Gemini client closed")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
