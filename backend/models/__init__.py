# backend/models/__init__.py
"""
Módulo de modelos adicionais.
Os modelos principais estão em backend/models.py
Este módulo contém modelos específicos organizados por domínio.

NOTA: Devido ao conflito de namespace entre backend/models.py e backend/models/,
re-exportamos os modelos principais aqui para garantir compatibilidade.
"""

# Importar modelos principais do models.py via import direto do módulo
import importlib.util
import os
from sqlalchemy.orm import DeclarativeBase

# Carregar o arquivo models.py diretamente para evitar conflito de namespace
_models_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "models.py")
_spec = importlib.util.spec_from_file_location("backend_models_main", _models_path)
_models_main = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_models_main)

# Exportar todos os atributos publicos do models.py
# Isso permite que qualquer modelo definido lá seja acessível via backend.models
_all_exports = []
for _name in dir(_models_main):
    if not _name.startswith('_'):
        _attr = getattr(_models_main, _name)
        globals()[_name] = _attr
        _all_exports.append(_name)

# Modelos de receita
from backend.models.revenue_models import (
    Plan,
    Contract,
    ContractItem,
    Invoice,
    InvoiceLineItem,
    Payment
)

from backend.models.ai_credit_models import (
    AICreditWallet,
    AIUsageEvent,
    AICreditTransaction,
)

from backend.models.ai_provider_models import AIProviderCredential

# Adicionar modelos de receita à lista de exports
_all_exports.extend([
    'Plan',
    'Contract',
    'ContractItem',
    'Invoice',
    'InvoiceLineItem',
    'Payment',
    'AICreditWallet',
    'AIUsageEvent',
    'AICreditTransaction',
    'AIProviderCredential',
])

__all__ = _all_exports
