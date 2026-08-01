"""
Model configuration for Agents SDK
Loads model settings from .env file
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env from agents_sdk directory
agents_sdk_dir = Path(__file__).parent.parent
env_path = agents_sdk_dir / '.env'

if env_path.exists():
    load_dotenv(env_path)

# Model configuration
DEFAULT_MODEL = os.getenv('OPENAI_MODEL', 'gpt-4o-mini')
MAX_TURNS = int(os.getenv('AGENT_MAX_TURNS', '10'))
TEMPERATURE = float(os.getenv('AGENT_TEMPERATURE', '0.7'))
ENABLE_TRACING = os.getenv('OPENAI_ENABLE_TRACING', 'true').lower() == 'true'

def get_model_config():
    """Get model configuration for agents"""
    return {
        'model': DEFAULT_MODEL,
        'max_turns': MAX_TURNS,
        'temperature': TEMPERATURE,
        'enable_tracing': ENABLE_TRACING
    }
