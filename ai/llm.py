import json
import asyncio
import logging
from typing import Optional, AsyncIterator
from config import settings

log = logging.getLogger("sikai")

# ── Lazy clients ──────────────────────────────────────────────────
_groq_client   = None
_openai_client = None


def get_provider() -> str:
    return getattr(settings, "ai_provider", "groq").lower()


def get_groq():
    global _groq_client
    if _groq_client is None:
        from groq import AsyncGroq
        _groq_client = AsyncGroq(api_key=settings.groq_api_key)
    return _groq_client


def get_openai():
    global _openai_client
    if _openai_client is None:
        from openai import AsyncOpenAI
        _openai_client = AsyncOpenAI(api_key=settings.openai_api_key)
    return _openai_client


def _smart_model() -> str:
    p = get_provider()
    if p == "openai": return "gpt-4o-mini"
    return settings.groq_model_smart


def _fast_model() -> str:
    p = get_provider()
    if p == "openai": return "gpt-4o-mini"
    return settings.groq_model_fast


# ═══════════════════════════════════════════════════════════════════
# CORE: TEXT COMPLETION
# ═══════════════════════════════════════════════════════════════════

async def llm_complete(
    system_prompt: str,
    user_prompt: str,
    model: str = None,
    max_tokens: int = 1000,
    temperature: float = 0.7,
    retries: int = 3,
    json_mode: bool = False,
) -> str:
    provider = get_provider()
    model = model or _smart_model()

    if provider == "openai":
        return await _openai_complete(
            system_prompt, user_prompt, model,
            max_tokens, temperature, retries, json_mode
        )
    return await _groq_complete(
        system_prompt, user_prompt, model,
        max_tokens, temperature, retries, json_mode
    )


async def _groq_complete(
    system_prompt, user_prompt, model,
    max_tokens, temperature, retries, json_mode
) -> str:
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
            text = response.choices[0].message.content.strip()
            log.debug(f"Groq | {model} | in={response.usage.prompt_tokens} out={response.usage.completion_tokens}")
            return text
        except Exception as e:
            wait = 2 ** attempt
            log.warning(f"Groq attempt {attempt+1}/{retries}: {e}. Retry in {wait}s")
            if attempt < retries - 1:
                await asyncio.sleep(wait)
            else:
                raise


async def _openai_complete(
    system_prompt, user_prompt, model,
    max_tokens, temperature, retries, json_mode
) -> str:
    client = get_openai()
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
            text = response.choices[0].message.content.strip()
            log.debug(f"OpenAI | {model} | in={response.usage.prompt_tokens} out={response.usage.completion_tokens}")
            return text
        except Exception as e:
            wait = 2 ** attempt
            log.warning(f"OpenAI attempt {attempt+1}/{retries}: {e}. Retry in {wait}s")
            if attempt < retries - 1:
                await asyncio.sleep(wait)
            else:
                raise


# ═══════════════════════════════════════════════════════════════════
# JSON COMPLETION
# ═══════════════════════════════════════════════════════════════════

async def llm_complete_json(
    system_prompt: str,
    user_prompt: str,
    model: str = None,
    max_tokens: int = 1000,
) -> dict:
    model = model or _smart_model()
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
        # Strip markdown code blocks if present
        clean = re.sub(r'```json\s*|\s*```', '', raw).strip()
        try:
            return json.loads(clean)
        except Exception:
            match = re.search(r'\{.*\}', clean, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group())
                except Exception:
                    pass
        log.error(f"Bad JSON from LLM: {raw[:300]}")
        raise ValueError("AI returned invalid JSON — please try again")


# ═══════════════════════════════════════════════════════════════════
# CHAT (multi-turn)
# ═══════════════════════════════════════════════════════════════════

async def llm_chat(
    system_prompt: str,
    messages: list,
    model: str = None,
    max_tokens: int = 800,
    temperature: float = 0.8,
) -> str:
    provider = get_provider()
    model    = model or _fast_model()
    full_messages = [{"role": "system", "content": system_prompt}] + messages

    try:
        if provider == "openai":
            client = get_openai()
        else:
            client = get_groq()

        response = await client.chat.completions.create(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=full_messages,
        )
        return response.choices[0].message.content.strip()

    except Exception as e:
        log.error(f"Chat error ({provider}): {e}")
        return "माफ गर्नुहोस्, AI अहिले busy छ। कृपया फेरि try गर्नुस्। 🙏"


# ═══════════════════════════════════════════════════════════════════
# STREAMING
# ═══════════════════════════════════════════════════════════════════

async def llm_stream(
    system_prompt: str,
    user_prompt: str,
    model: str = None,
    max_tokens: int = 800,
) -> AsyncIterator[str]:
    provider = get_provider()
    model    = model or _fast_model()

    try:
        if provider == "openai":
            client = get_openai()
        else:
            client = get_groq()

        stream = await client.chat.completions.create(
            model=model,
            max_tokens=max_tokens,
            temperature=0.8,
            stream=True,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_prompt},
            ],
        )
        async for chunk in stream:
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta

    except Exception as e:
        log.error(f"Stream error ({provider}): {e}")
        yield "माफ गर्नुहोस्, streaming error। फेरि try गर्नुस्।"


# ═══════════════════════════════════════════════════════════════════
# SAFETY CHECK
# ═══════════════════════════════════════════════════════════════════

async def check_content_safety(topic: str) -> dict:
    from ai.prompts import SAFETY_CHECK_SYSTEM, SAFETY_CHECK_USER
    try:
        result = await llm_complete_json(
            system_prompt=SAFETY_CHECK_SYSTEM,
            user_prompt=SAFETY_CHECK_USER.format(topic=topic),
            model=_fast_model(),
            max_tokens=120,
        )
        return result
    except Exception:
        return {"safe": True, "reason": "safety check unavailable", "caution": None}
