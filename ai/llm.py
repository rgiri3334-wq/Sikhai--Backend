import json
import asyncio
import logging
from typing import Optional, AsyncIterator
from config import settings

log = logging.getLogger("sikai")

# ═══════════════════════════════════════════════════════════════════
# MULTI-PROVIDER LLM CLIENT
# Supports: Groq (Llama 3), OpenAI (GPT-4o), Google (Gemini)
# Set AI_PROVIDER in Railway variables to switch
# ═══════════════════════════════════════════════════════════════════

# Lazy-loaded clients
_groq_client   = None
_openai_client = None


def get_provider() -> str:
    """
    Determine which AI provider to use.
    Set AI_PROVIDER in Railway environment variables:
      "groq"   → Llama 3 via Groq (default, free tier available)
      "openai" → GPT-4o Mini via OpenAI (better Nepali)
      "gemini" → Gemini Flash via Google (alternative)
    """
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


def get_model(speed: str = "smart") -> str:
    """
    Return the right model name based on provider and speed setting.
    speed: "smart" for best quality, "fast" for speed/cost
    """
    provider = get_provider()

    if provider == "openai":
        # GPT-4o Mini for both — great quality, much cheaper than GPT-4o
        return "gpt-4o-mini" if speed == "fast" else "gpt-4o-mini"

    if provider == "gemini":
        # Gemini Flash for fast, Pro for smart
        return "gemini-1.5-flash" if speed == "fast" else "gemini-1.5-pro"

    # Default: Groq + Llama 3
    return settings.groq_model_fast if speed == "fast" else settings.groq_model_smart


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
    speed: str = "smart",
) -> str:
    """
    Complete a prompt using the configured AI provider.
    Automatically handles Groq, OpenAI, or Gemini based on settings.
    """
    provider = get_provider()
    model    = model or get_model(speed)

    if provider == "openai":
        return await _openai_complete(
            system_prompt, user_prompt, model, max_tokens,
            temperature, retries, json_mode
        )
    elif provider == "gemini":
        return await _gemini_complete(
            system_prompt, user_prompt, model, max_tokens,
            temperature, retries
        )
    else:
        return await _groq_complete(
            system_prompt, user_prompt, model, max_tokens,
            temperature, retries, json_mode
        )


# ═══════════════════════════════════════════════════════════════════
# GROQ IMPLEMENTATION (Llama 3)
# ═══════════════════════════════════════════════════════════════════

async def _groq_complete(
    system_prompt, user_prompt, model,
    max_tokens, temperature, retries, json_mode
) -> str:
    client = get_groq()
    kwargs = {
        "model":       model,
        "max_tokens":  max_tokens,
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
            log.debug(f"Groq | model={model} | in={response.usage.prompt_tokens} out={response.usage.completion_tokens}")
            return text
        except Exception as e:
            wait = 2 ** attempt
            log.warning(f"Groq attempt {attempt+1}/{retries}: {e}. Retry in {wait}s")
            if attempt < retries - 1:
                await asyncio.sleep(wait)
            else:
                raise


# ═══════════════════════════════════════════════════════════════════
# OPENAI IMPLEMENTATION (GPT-4o Mini / GPT-4o)
# ═══════════════════════════════════════════════════════════════════

async def _openai_complete(
    system_prompt, user_prompt, model,
    max_tokens, temperature, retries, json_mode
) -> str:
    client = get_openai()
    kwargs = {
        "model":       model,
        "max_tokens":  max_tokens,
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
            log.debug(f"OpenAI | model={model} | in={response.usage.prompt_tokens} out={response.usage.completion_tokens}")
            return text
        except Exception as e:
            wait = 2 ** attempt
            log.warning(f"OpenAI attempt {attempt+1}/{retries}: {e}. Retry in {wait}s")
            if attempt < retries - 1:
                await asyncio.sleep(wait)
            else:
                raise


# ═══════════════════════════════════════════════════════════════════
# GEMINI IMPLEMENTATION (Google)
# ═══════════════════════════════════════════════════════════════════

async def _gemini_complete(
    system_prompt, user_prompt, model,
    max_tokens, temperature, retries
) -> str:
    try:
        import google.generativeai as genai
        genai.configure(api_key=settings.gemini_api_key)
        gemini_model = genai.GenerativeModel(
            model_name=model,
            system_instruction=system_prompt,
        )
        for attempt in range(retries):
            try:
                response = await asyncio.to_thread(
                    gemini_model.generate_content,
                    user_prompt,
                    generation_config={"max_output_tokens": max_tokens, "temperature": temperature},
                )
                return response.text.strip()
            except Exception as e:
                wait = 2 ** attempt
                log.warning(f"Gemini attempt {attempt+1}/{retries}: {e}. Retry in {wait}s")
                if attempt < retries - 1:
                    await asyncio.sleep(wait)
                else:
                    raise
    except ImportError:
        raise RuntimeError("google-generativeai package not installed. Add to requirements.txt")


# ═══════════════════════════════════════════════════════════════════
# CORE: JSON COMPLETION
# ═══════════════════════════════════════════════════════════════════

async def llm_complete_json(
    system_prompt: str,
    user_prompt: str,
    model: str = None,
    max_tokens: int = 1000,
    speed: str = "smart",
) -> dict:
    """Complete a prompt and parse the result as JSON."""
    model = model or get_model(speed)
    raw = await llm_complete(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        model=model,
        max_tokens=max_tokens,
        temperature=0.3,
        json_mode=(get_provider() != "gemini"),  # Gemini doesn't support json_mode
        speed=speed,
    )
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # Try extracting JSON from response
        import re
        match = re.search(r'\{.*\}', raw, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except Exception:
                pass
        log.error(f"Failed to parse JSON from LLM: {raw[:300]}")
        raise ValueError("AI returned invalid JSON — please try again")


# ═══════════════════════════════════════════════════════════════════
# CORE: CHAT (multi-turn conversation)
# ═══════════════════════════════════════════════════════════════════

async def llm_chat(
    system_prompt: str,
    messages: list,
    model: str = None,
    max_tokens: int = 800,
    temperature: float = 0.8,
    speed: str = "fast",
) -> str:
    """Multi-turn chat completion for AI tutor conversations."""
    provider = get_provider()
    model    = model or get_model(speed)

    try:
        if provider == "openai":
            client = get_openai()
            full_messages = [{"role": "system", "content": system_prompt}] + messages
            response = await client.chat.completions.create(
                model=model, max_tokens=max_tokens,
                temperature=temperature, messages=full_messages,
            )
            return response.choices[0].message.content.strip()

        elif provider == "gemini":
            return await _gemini_complete(
                system_prompt,
                # Flatten message history for Gemini
                "\n".join([f"{m['role']}: {m['content']}" for m in messages]),
                model, max_tokens, temperature, 3
            )

        else:
            # Groq
            client = get_groq()
            full_messages = [{"role": "system", "content": system_prompt}] + messages
            response = await client.chat.completions.create(
                model=model, max_tokens=max_tokens,
                temperature=temperature, messages=full_messages,
            )
            return response.choices[0].message.content.strip()

    except Exception as e:
        log.error(f"Chat LLM error ({provider}): {e}")
        return "माफ गर्नुहोस्, अहिले AI busy छ। कृपया फेरि try गर्नुस्। 🙏"


# ═══════════════════════════════════════════════════════════════════
# CORE: STREAMING
# ═══════════════════════════════════════════════════════════════════

async def llm_stream(
    system_prompt: str,
    user_prompt: str,
    model: str = None,
    max_tokens: int = 800,
    speed: str = "fast",
) -> AsyncIterator[str]:
    """Streaming text generation for real-time tutor responses."""
    provider = get_provider()
    model    = model or get_model(speed)

    try:
        if provider == "openai":
            client = get_openai()
            stream = await client.chat.completions.create(
                model=model, max_tokens=max_tokens, temperature=0.8,
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

        else:
            # Groq streaming
            client = get_groq()
            stream = await client.chat.completions.create(
                model=model, max_tokens=max_tokens, temperature=0.8,
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
        yield "माफ गर्नुहोस्, streaming error भयो। फेरि try गर्नुस्।"


# ═══════════════════════════════════════════════════════════════════
# CONTENT SAFETY CHECK
# ═══════════════════════════════════════════════════════════════════

async def check_content_safety(topic: str) -> dict:
    """Check if a topic is safe for Nepal's educational platform."""
    from ai.prompts import SAFETY_CHECK_SYSTEM, SAFETY_CHECK_USER
    try:
        result = await llm_complete_json(
            system_prompt=SAFETY_CHECK_SYSTEM,
            user_prompt=SAFETY_CHECK_USER.format(topic=topic),
            max_tokens=120,
            speed="fast",
        )
        return result
    except Exception as e:
        log.warning(f"Safety check failed: {e} — defaulting to safe")
        return {"safe": True, "reason": "safety check unavailable", "caution": None}
