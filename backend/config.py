import os
from pathlib import Path
from dotenv import load_dotenv

# Carregar arquivo .env baseado na variável de ambiente
ENV_FILE = os.getenv('ENV_FILE', '.env')
env_path = Path(__file__).parent / ENV_FILE
load_dotenv(env_path)

# Configurações existentes
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
GOOGLE_SHEETS_CREDENTIALS_PATH = os.getenv("GOOGLE_SHEETS_CREDENTIALS_PATH", "")
GOOGLE_CALENDAR_CREDENTIALS_PATH = os.getenv("GOOGLE_CALENDAR_CREDENTIALS_PATH", "")
REACT_APP_API_URL = os.getenv("REACT_APP_API_URL", "")
CHAT_MEMORY_DIR = os.getenv("CHAT_MEMORY_DIR", "")

# Novas configurações para ambientes
ENVIRONMENT = os.getenv('ENVIRONMENT', 'production')
DEBUG = os.getenv('DEBUG', 'False').lower() == 'true'
REDIS_URL = os.getenv('REDIS_URL', 'redis://localhost:6379/0')


def _required_env(name: str, default_dev: str = "") -> str:
    value = os.getenv(name)
    if value:
        return value
    if ENVIRONMENT == "production":
        raise RuntimeError(f"{name} environment variable is required in production")
    return default_dev


DATABASE_URL = _required_env('DATABASE_URL', 'sqlite:///./dev.db')
CLIENT_TOKEN = os.getenv('CLIENT_TOKEN', '').strip()

# URL pública do servidor (para gerar URLs de mídia)
PUBLIC_BASE_URL = _required_env('PUBLIC_BASE_URL', 'http://127.0.0.1:8002')

# ==========================================
# WAHA Configuration (WhatsApp HTTP API)
# ==========================================
WAHA_ENABLED = os.getenv('WAHA_ENABLED', 'true').lower() == 'true'
WAHA_BASE_URL = os.getenv('WAHA_BASE_URL', 'http://localhost:3000')
WAHA_API_KEY = (
    _required_env('WAHA_API_KEY')
    if WAHA_ENABLED
    else os.getenv('WAHA_API_KEY', '').strip()
)

def is_development():
    return ENVIRONMENT == 'development'

def is_production():
    return ENVIRONMENT == 'production'
