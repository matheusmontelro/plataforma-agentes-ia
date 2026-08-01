"""
Company Data Service - Manages company-specific configuration data
Separated from prompts - this handles only DATA, not instructions
"""

import json
import hashlib
import logging
from typing import Dict, Any, Optional
from sqlalchemy.orm import Session
from sqlalchemy import text
from ..database.models import CompanyEmbedding

logger = logging.getLogger(__name__)

class CompanyDataService:
    """
    Service to manage company configuration data from agent_config
    This is ONLY for data management, not prompt generation
    """

    def __init__(self, db: Session):
        self.db = db

    def get_company_data(self, company_id: int) -> Dict[str, Any]:
        """
        Get processed company data for use in agent context

        Returns:
            Dict with structured company data (not prompt instructions)
        """
        try:
            # Check if processed data exists and is current
            embedding = self._get_existing_embedding(company_id)
            current_config_hash = self._get_current_config_hash(company_id)

            if embedding and embedding.config_hash == current_config_hash:
                logger.info(f"✅ Using cached data for company {company_id}")
                return {
                    "company_info": embedding.company_info or {},
                    "services_info": embedding.services_info or {},
                    "financial_info": embedding.financial_info or {},
                    "conversation_patterns": embedding.conversation_patterns or {}
                }

            # Generate new processed data
            logger.info(f"🔄 Processing new data for company {company_id}")
            return self._process_and_save_data(company_id)

        except Exception as e:
            logger.error(f"❌ Error getting data for company {company_id}: {e}")
            return self._get_fallback_data(company_id)

    def _get_existing_embedding(self, company_id: int) -> Optional[CompanyEmbedding]:
        """Get existing embedding from database"""
        try:
            return self.db.query(CompanyEmbedding).filter_by(company_id=company_id).first()
        except Exception as e:
            logger.error(f"Error querying company_embeddings: {e}")
            # Rollback failed transaction and return None to force fallback data
            self.db.rollback()
            return None

    def _get_agent_config(self, company_id: int) -> Dict[str, Any]:
        """Fetch agent configuration from database"""
        result = self.db.execute(text("""
            SELECT assistant_identity, company_info, team_and_specialties,
                   scheduling_config, financial_config, conversation_flow
            FROM agent_configurations
            WHERE company_id = :company_id
        """), {"company_id": company_id}).fetchone()

        if not result:
            return {}

        config = {}
        for key, value in result._mapping.items():
            if value:
                config[key] = value if isinstance(value, dict) else json.loads(value or "{}")

        return config

    def _get_current_config_hash(self, company_id: int) -> str:
        """Generate hash of current configuration"""
        config = self._get_agent_config(company_id)
        config_json = json.dumps(config, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(config_json.encode()).hexdigest()

    def _process_company_data(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process raw agent_config into structured company data
        This is ONLY data processing, not prompt generation
        """
        processed_data = {}

        # Process company information
        company_info = config.get("company_info", {})
        processed_data["company_info"] = {
            "name": company_info.get("name", ""),
            "address": company_info.get("address", ""),
            "phone": company_info.get("phone", ""),
            "services_summary": company_info.get("services", "")
        }

        # Process assistant identity
        identity = config.get("assistant_identity", {})
        processed_data["assistant_identity"] = {
            "name": identity.get("name", ""),
            "personality": identity.get("personality", ""),
            "tone": identity.get("tone", "")
        }

        # Process team and specialties
        team = config.get("team_and_specialties", {})
        processed_data["services_info"] = {
            "specialties": team.get("specialties", []),
            "professionals": team.get("professionals", [])
        }

        # Process scheduling configuration
        scheduling = config.get("scheduling_config", {})
        processed_data["scheduling_info"] = {
            "working_hours": scheduling.get("working_hours", ""),
            "advance_booking_days": scheduling.get("advance_booking_days", 30)
        }

        # Process financial information
        financial = config.get("financial_config", {})
        processed_data["financial_info"] = {
            "services": financial.get("services", []),
            "payment_methods": financial.get("payment_methods", [])
        }

        # Process conversation patterns
        flow = config.get("conversation_flow", {})
        processed_data["conversation_patterns"] = {
            "greeting_style": flow.get("greeting_style", ""),
            "objection_handling": flow.get("objection_handling", [])
        }

        return processed_data

    def _process_and_save_data(self, company_id: int) -> Dict[str, Any]:
        """Process and save company data to database"""
        config = self._get_agent_config(company_id)

        if not config:
            logger.warning(f"No agent config found for company {company_id}")
            return self._get_fallback_data(company_id)

        # Process data
        processed_data = self._process_company_data(config)
        config_hash = self._get_current_config_hash(company_id)

        # Save to database
        existing = self._get_existing_embedding(company_id)
        if existing:
            # Update existing
            existing.config_hash = config_hash
            existing.company_info = processed_data.get("company_info", {})
            existing.services_info = processed_data.get("services_info", {})
            existing.financial_info = processed_data.get("financial_info", {})
            existing.conversation_patterns = processed_data.get("conversation_patterns", {})
            # Note: instructions field is no longer used for prompts
            existing.instructions = ""  # Keep empty since prompts are now separate
        else:
            # Create new
            embedding = CompanyEmbedding(
                company_id=company_id,
                instructions="",  # No longer store instructions here
                config_hash=config_hash,
                company_info=processed_data.get("company_info", {}),
                services_info=processed_data.get("services_info", {}),
                financial_info=processed_data.get("financial_info", {}),
                conversation_patterns=processed_data.get("conversation_patterns", {})
            )
            self.db.add(embedding)

        self.db.commit()
        logger.info(f"✅ Saved processed data for company {company_id}")

        return processed_data

    def _get_fallback_data(self, company_id: int) -> Dict[str, Any]:
        """Get fallback data when config is not available"""
        return {
            "company_info": {
                "name": f"Empresa {company_id}",
                "address": "",
                "phone": "",
                "services_summary": ""
            },
            "assistant_identity": {
                "name": "Assistente Virtual",
                "personality": "Cordial e profissional",
                "tone": "Atencioso"
            },
            "services_info": {
                "specialties": [],
                "professionals": []
            },
            "scheduling_info": {
                "working_hours": "",
                "advance_booking_days": 30
            },
            "financial_info": {
                "services": [],
                "payment_methods": []
            },
            "conversation_patterns": {
                "greeting_style": "",
                "objection_handling": []
            }
        }

    def invalidate_embedding(self, company_id: int):
        """Force regeneration of embedding on next request"""
        try:
            embedding = self._get_existing_embedding(company_id)
            if embedding:
                embedding.config_hash = "invalid"
                self.db.commit()
                logger.info(f"✅ Invalidated embedding for company {company_id}")
        except Exception as e:
            logger.error(f"❌ Error invalidating embedding for company {company_id}: {e}")

    def get_company_info_summary(self, company_id: int) -> Dict[str, Any]:
        """Get structured company information for debugging"""
        try:
            embedding = self._get_existing_embedding(company_id)
            if embedding:
                return {
                    "company_id": company_id,
                    "has_embedding": True,
                    "config_hash": embedding.config_hash,
                    "company_info": embedding.company_info,
                    "services_count": len(embedding.services_info.get("specialties", [])),
                    "professionals_count": len(embedding.services_info.get("professionals", [])),
                    "updated_at": embedding.updated_at.isoformat()
                }
            else:
                return {
                    "company_id": company_id,
                    "has_embedding": False
                }
        except Exception as e:
            return {
                "company_id": company_id,
                "error": str(e)
            }