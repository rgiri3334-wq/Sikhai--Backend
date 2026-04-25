import json
import asyncio
import logging
from groq import AsyncGroq
from typing import Optional, AsyncIterator
from config import settings

log = logging.getLogger("sikai")
_groq_client: Optional[AsyncGroq] = None


def get_groq() -> AsyncGroq:
    global _groq_client
    if _groq_client is None:
        _groq_client = AsyncGroq(api_key=settings.groq_api_key)
    return _groq_client


async def llm_complete(
    system_prompt: str,
    user_prompt: str,
    model: str = None,
    max_tokens: int = 1000,
    temperature: float = 0.7,
    retries: int = 3,
    json_mode: bool = False,
) -> str:
    model = model or settings.groq_model_smart
    client = get_groq()

    kwargs = {
        "model": model,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_prompt},
        ],
    }
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}

    for attempt in range(retries):
        try:
            response = await client.chat.completions.create(**kwargs)
            return response.choices[0].message.content.strip()
        except Exception as e:
            wait = 2 ** attempt
            log.warning(f"LLM attempt {attempt+1}/{retries} failed: {e}. Retry in {wait}s")
            if attempt < retries - 1:
                await asyncio.sleep(wait)
            else:
                raise


async def llm_complete_json(
    system_prompt: str,
    user_prompt: str,
    model: str = None,
    max_tokens: int = 1000,
) -> dict:
    model = model or settings.groq_model_smart
    raw = await llm_complete(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        model=model,
        max_tokens=max_tokens,
        temperature=0.3,
        json_mode=True,
    )
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        import re
        match = re.search(r'\{.*\}', raw, re.DOTALL)
        if match:
            return json.loads(match.group())
        log.error(f"Bad JSON from LLM: {raw[:200]}")
        raise ValueError("LLM returned invalid JSON")


async def llm_chat(
    system_prompt: str,
    messages: list,
    model: str = None,
    max_tokens: int = 800,
    temperature: float = 0.8,
) -> str:
    model = model or settings.groq_model_fast
    client = get_groq()
    full_messages = [{"role": "system", "content": system_prompt}] + messages
    try:
        response = await client.chat.completions.create(
            model=model, max_tokens=max_tokens,
            temperature=temperature, messages=full_messages,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        log.error(f"Chat LLM error: {e}")
        return "माफ गर्नुहोस्, AI अहिले busy छ। फेरि try गर्नुस्।"


async def llm_stream(
    system_prompt: str,
    user_prompt: str,
    model: str = None,
    max_tokens: int = 800,
) -> AsyncIterator[str]:
    model = model or settings.groq_model_fast
    client = get_groq()
    stream = await client.chat.completions.create(
        model=model, max_tokens=max_tokens, temperature=0.8, stream=True,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_prompt},
        ],
    )
    async for chunk in stream:
        delta = chunk.choices[0].delta.content
        if delta:
            yield delta


async def check_content_safety(topic: str) -> dict:
    from ai.prompts import SAFETY_CHECK_SYSTEM, SAFETY_CHECK_USER
    try:
        result = await llm_complete_json(
            system_prompt=SAFETY_CHECK_SYSTEM,
            user_prompt=SAFETY_CHECK_USER.format(topic=topic),
            model=settings.groq_model_fast,
            max_tokens=100,
        )
        return result
    except Exception:
        return {"safe": True, "reason": "safety check unavailable"}
