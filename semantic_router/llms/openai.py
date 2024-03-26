import os
from typing import List, Optional

import openai
from pydantic import PrivateAttr

from semantic_router.llms.base import BaseLLM
from semantic_router.schema import Message
from semantic_router.utils.defaults import EncoderDefault
from semantic_router.utils.logger import logger


class OpenAILLM(BaseLLM):
    temperature: float = 0.01
    max_tokens: int = 200
    _client: Optional[openai.OpenAI] = PrivateAttr()

    def __init__(
        self,
        name: Optional[str] = None,
        openai_api_key: Optional[str] = None,
        temperature: float = 0.01,
        max_tokens: int = 200,
    ):
        if name is None:
            name = EncoderDefault.OPENAI.value["language_model"]
        super().__init__(name=name, temperature=temperature, max_tokens=max_tokens)
        api_key = openai_api_key or os.getenv("OPENAI_API_KEY")
        if api_key is None:
            raise ValueError("OpenAI API key cannot be 'None'.")
        try:
            self._client = openai.OpenAI(api_key=api_key)
        except Exception as e:
            raise ValueError(f"OpenAI API client failed to initialize. Error: {e}")

    def __call__(self, messages: List[Message]) -> str:
        if self._client is None:
            raise ValueError("OpenAI client is not initialized.")
        try:
            completion = self._client.chat.completions.create(
                model=self.name,
                messages=[m.to_openai() for m in messages],
                temperature=self.temperature,
                max_tokens=self.max_tokens,
            )

            output = completion.choices[0].message.content

            if not output:
                raise Exception("No output generated")
            return output
        except Exception as e:
            logger.error(f"LLM error: {e}")
            raise Exception(f"LLM error: {e}") from e
