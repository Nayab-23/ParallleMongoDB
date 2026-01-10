import json
import logging
import os
from typing import Optional, Dict, Any

import requests
from openai import OpenAI

logger = logging.getLogger(__name__)


class LLMService:
    """
    Hybrid LLM service:
    - Uses Ollama (Llama 3.1 8B) for workflow automation
    - Uses OpenAI (GPT-4) for chat and brief generation
    """

    def __init__(self):
        fireworks_key = os.getenv("FIREWORKS_API_KEY", "").strip()
        openai_key = os.getenv("OPENAI_API_KEY", "").strip()
        base_url = None
        api_key = None
        if fireworks_key:
            api_key = fireworks_key
            base_url = os.getenv("FIREWORKS_BASE_URL", "https://api.fireworks.ai/inference/v1").strip()
        elif openai_key:
            api_key = openai_key
            base_url = os.getenv("OPENAI_BASE_URL", "").strip() or None

        self.openai_client = OpenAI(api_key=api_key, base_url=base_url) if api_key else None
        self.ollama_url = os.getenv("OLLAMA_URL", "http://localhost:11434")

    def call_openai(
        self,
        messages: list,
        model: str = "gpt-4",
        temperature: float = 0.7,
        max_tokens: int = 1000,
    ) -> str:
        """Use OpenAI for chat and brief generation."""
        if self.openai_client is None:
            raise RuntimeError("LLM client not configured. Set FIREWORKS_API_KEY or OPENAI_API_KEY.")
        response = self.openai_client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return response.choices[0].message.content

    def call_ollama(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.2,
        expect_json: bool = True,
    ) -> str:
        """Use Ollama for workflow automation."""

        full_prompt = f"{system_prompt}\n\n{prompt}" if system_prompt else prompt

        try:
            response = requests.post(
                f"{self.ollama_url}/api/generate",
                json={
                    "model": "llama3.1:8b",
                    "prompt": full_prompt,
                    "stream": False,
                    "options": {
                        "temperature": temperature,
                        "num_predict": 500 if expect_json else 1000,
                    },
                },
                timeout=30,
            )

            response.raise_for_status()
            result = response.json()["response"]

            # Clean up JSON if expected
            if expect_json:
                # Remove markdown code fences if present
                result = result.replace("```json", "").replace("```", "").strip()

            return result

        except requests.exceptions.ConnectionError:
            logger.error(f"Ollama server not running at {self.ollama_url}")
            raise Exception("Ollama server not running. Start with: ollama serve")
        except Exception as e:
            logger.error(f"Ollama error: {str(e)}")
            raise Exception(f"Ollama error: {str(e)}")

    def detect_workflow_pattern(
        self,
        action_sequences: list,
    ) -> Dict[str, Any]:
        """
        Analyze user action sequences to detect workflow patterns.
        Uses Ollama for pattern recognition.

        Returns:
        {
            "pattern_name": str,
            "trigger": str,
            "steps": list,
            "confidence": float
        }
        """

        system_prompt = """You are a workflow automation detector.
Analyze user action sequences and identify repeated patterns.
Return ONLY valid JSON, no extra text.

Required format:
{
  "pattern_name": "Short name (2-4 words)",
  "trigger": "What starts this workflow",
  "steps": ["Action 1", "Action 2"],
  "confidence": 0.0-1.0
}"""

        prompt = f"""Analyze these workflows and find the common pattern:

{json.dumps(action_sequences, indent=2)}

Return JSON with: pattern_name, trigger, steps, confidence"""

        result = self.call_ollama(
            prompt=prompt,
            system_prompt=system_prompt,
            temperature=0.2,
            expect_json=True,
        )

        try:
            return json.loads(result)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse Ollama JSON: {result}")
            raise Exception(f"Ollama returned invalid JSON: {str(e)}")

    def name_workflow(
        self,
        action_sequence: list,
    ) -> str:
        """
        Generate a short, memorable name for a workflow.
        Uses Ollama for creative naming.
        """

        system_prompt = "You are a workflow naming expert. Give workflows short, memorable names (2-4 words)."

        prompt = f"""Give this workflow a short name:

{json.dumps(action_sequence, indent=2)}

Return only the name, nothing else."""

        return self.call_ollama(
            prompt=prompt,
            system_prompt=system_prompt,
            temperature=0.7,
            expect_json=False,
        ).strip()


# Create singleton instance
llm_service = LLMService()
