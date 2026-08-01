"""
Gender Detection Service - Uses LLM to detect gender from assistant names
More reliable than hardcoded lists for Brazilian names
"""

import logging
import openai
from typing import Optional
from backend.services.ai_provider_service import (
    AIProviderCredentialError,
    get_company_openai_api_key,
)

logger = logging.getLogger(__name__)

async def detect_gender_from_name_llm(
    name: str,
    *,
    api_key: str,
) -> Optional[str]:
    """
    Use OpenAI LLM to detect gender from assistant name.
    More accurate than hardcoded lists, especially for Brazilian names.

    Args:
        name: Assistant name

    Returns:
        'male', 'female', or None if cannot determine
    """
    if not name or not isinstance(name, str):
        logger.warning(f"Invalid name provided: {name}")
        return None

    try:
        client = openai.AsyncOpenAI(api_key=api_key)

        prompt = f"""
Analyze the Brazilian name "{name}" and determine if it's typically masculine or feminine.

Instructions:
- Consider Brazilian Portuguese naming conventions
- Look at the first name only if multiple names provided
- Return ONLY one word: "masculine" or "feminine"
- If you cannot determine with high confidence, return "unknown"

Name to analyze: {name}

Response (one word only):"""

        logger.info(f"Using LLM to detect gender for name: '{name}'")

        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are an expert in Brazilian names and gender classification. Respond with exactly one word: 'masculine', 'feminine', or 'unknown'."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=10,
            temperature=0  # Deterministic response
        )

        result = response.choices[0].message.content.strip().lower()
        logger.info(f"LLM response for '{name}': '{result}'")

        # Map response to our gender format
        if result == "masculine":
            logger.info(f"Name '{name}' detected as MALE by LLM")
            return "male"
        elif result == "feminine":
            logger.info(f"Name '{name}' detected as FEMALE by LLM")
            return "female"
        else:
            logger.warning(f"LLM could not determine gender for '{name}': {result}")
            return None

    except Exception as e:
        logger.error(
            "Error using LLM for gender detection: %s",
            type(e).__name__,
        )
        return None

def get_voice_for_gender(gender: Optional[str], default_voice: str = "nova") -> str:
    """
    Get appropriate OpenAI voice based on gender.

    Args:
        gender: 'male', 'female', or None
        default_voice: Default voice if gender is unknown

    Returns:
        OpenAI voice name
    """
    if gender == 'male':
        voice = "cedar"  # Male voice - deeper, more masculine
        logger.info(f"Selected MALE voice: {voice}")
        return voice
    elif gender == 'female':
        voice = "marin"  # Female voice - softer, more feminine
        logger.info(f"Selected FEMALE voice: {voice}")
        return voice
    else:
        logger.info(f"Using default voice: {default_voice} (gender unknown)")
        return default_voice

# Cache para evitar chamadas desnecessárias ao LLM
_gender_cache = {}

async def get_assistant_voice_from_db(db, company_id: int, default_voice: str = "nova") -> str:
    """
    Get appropriate voice based on assistant name from database.
    Uses LLM for gender detection with caching.

    Args:
        db: Database session
        company_id: Company ID
        default_voice: Default voice if cannot determine

    Returns:
        OpenAI voice name
    """
    try:
        from sqlalchemy import text

        # Get assistant name from agent_configurations
        result = db.execute(
            text("SELECT assistant_identity FROM agent_configurations WHERE company_id = :cid LIMIT 1"),
            {"cid": company_id}
        ).fetchone()

        if not result or not result.assistant_identity:
            logger.warning(f"No assistant configuration found for company {company_id}")
            return default_voice

        assistant_name = result.assistant_identity.get('assistant_name', '').strip()

        if not assistant_name:
            logger.warning(f"No assistant name found for company {company_id}")
            return default_voice

        logger.info(f"Found assistant name for company {company_id}: '{assistant_name}'")

        # Check cache first
        if assistant_name in _gender_cache:
            gender = _gender_cache[assistant_name]
            logger.info(f"Using cached gender for '{assistant_name}': {gender}")
        else:
            # Use LLM to detect gender
            try:
                api_key = get_company_openai_api_key(db, company_id)
            except AIProviderCredentialError:
                logger.info(
                    "Gender detection skipped: company OpenAI key unavailable company_id=%s",
                    company_id,
                )
                return default_voice
            gender = await detect_gender_from_name_llm(
                assistant_name,
                api_key=api_key,
            )
            # Cache the result
            _gender_cache[assistant_name] = gender
            logger.info(f"Cached gender for '{assistant_name}': {gender}")

        return get_voice_for_gender(gender, default_voice)

    except Exception as e:
        logger.error(
            "Error getting assistant voice for company %s: %s",
            company_id,
            type(e).__name__,
        )
        return default_voice

# Test function
async def test_gender_detection():
    """Test LLM gender detection with known names"""
    test_names = ["Elisa", "David", "Fernanda", "João", "Maria", "Carlos", "Agatha"]

    print("Testing LLM gender detection:")
    for name in test_names:
        api_key = input("OpenAI API key: ").strip()
        gender = await detect_gender_from_name_llm(name, api_key=api_key)
        voice = get_voice_for_gender(gender)
        print(f"'{name}' -> {gender} (voice: {voice})")

if __name__ == "__main__":
    import asyncio
    asyncio.run(test_gender_detection())
