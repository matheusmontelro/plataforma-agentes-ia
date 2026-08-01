"""
Lead Tools - Function tools for managing lead lifecycle
"""
import logging
from typing import Dict, Any, Optional, List
from sqlalchemy.orm import Session
from sqlalchemy import text, func

# Import OpenAI Agents SDK components
from agents import function_tool, RunContextWrapper

logger = logging.getLogger(__name__)

def create_lead_tools(company_id: int, lead_config: Dict[str, Any] = None, phone: str = ""):
    """
    Create lead management tools with configuration context
    """
    if lead_config is None:
        lead_config = {}

    target_stage_id = lead_config.get('target_stage_id')
    default_media_source = lead_config.get('media_source', 'Agente IA')

    @function_tool
    async def manage_lead_lifecycle(
        context: RunContextWrapper,
        action: str,
        name: str = "",
        stage_name: str = "",
        notes: str = ""
    ) -> str:
        """
        Gerencia o ciclo de vida do Lead no CRM.

        Use esta ferramenta quando:
        1. O cliente informa o nome (action="update_info")
        2. O cliente demonstra interesse ou agenda (action="update_stage" ou "create")
        3. Identificar um novo lead (action="create")

        Args:
            action: Ação a realizar: "create" (criar novo), "update_info" (atualizar dados), "update_stage" (mudar etapa)
            name: Nome do cliente (se informado)
            stage_name: Nome da etapa para mover (ex: "Agendou", "Interesse", "Novo")
            notes: Notas ou observações para adicionar ao lead

        Returns:
            Mensagem de sucesso ou erro
        """
        try:
            from backend.db import get_db
            from backend.models import Lead, Contact, Pipeline, PipelineStage, Client

            db = next(get_db())

            # Resolve phone number
            current_phone = phone
            if not current_phone and hasattr(context, 'context') and hasattr(context.context, 'phone'):
                 current_phone = context.context.phone

            if not current_phone:
                return "Erro: Telefone não identificado."

            # SANITIZATION: Remove "+" prefix if present to standardize on "55..."
            current_phone = current_phone.replace("+", "")
            logger.info(f"[LeadTool] Sanitized phone: {current_phone}")

            logger.info(f"[LeadTool] Action: {action}, Phone: {current_phone}, Name: {name}, Stage: {stage_name}")

            # Find existing lead
            lead = db.query(Lead).filter(
                Lead.company_id == company_id,
                Lead.phone == current_phone
            ).first()

            # Find client_id for this company (needed for creation)
            # Usually leads are linked to a client (tenant).
            # We need to find the client_id associated with this company.
            # Assuming 1 company belongs to 1 client usually, or we search via ClientCompany.
            # Fallback: query company owner

            if not lead and action in ["create", "update_info", "update_stage"]:
                # Logic to create lead
                # 1. Get Client ID
                # Try to find from Company table? Company has no client_id directly usually,
                # but ClientCompany table links them.
                # Or use existing Contact?

                # Check Contact first
                contact = db.query(Contact).filter(
                    Contact.company_id == company_id,
                    Contact.phone == current_phone
                ).first()

                client_id = contact.client_id if contact else None

                if not client_id:
                     # Query ClientCompany to find owner
                     # This might be ambiguous if multiple clients manage one company, but usually 1-1 or main owner.
                     from backend.models import ClientCompany
                     cc = db.query(ClientCompany).filter(ClientCompany.company_id == company_id).first()
                     if cc:
                         client_id = cc.client_id

                if not client_id:
                     return "Erro: Cliente proprietário da empresa não encontrado."

                # Ensure Contact exists
                if not contact:
                    contact = Contact(
                        company_id=company_id,
                        client_id=client_id,
                        phone=current_phone,
                        name=name or "Novo Lead"
                    )
                    db.add(contact)
                    db.flush() # Generate ID if needed, though phone is key
                    logger.info(f"[LeadTool] Created new contact for {current_phone}")

                # Create Lead
                lead = Lead(
                    company_id=company_id,
                    client_id=client_id,
                    phone=current_phone,
                    name=name or (contact.name if contact else "Novo Lead"),
                    source_id=default_media_source,
                    current_stage_id=target_stage_id # Set initial stage from config
                )
                if target_stage_id:
                     # Attempt to set pipeline_id as well
                     stage = db.query(PipelineStage).filter(PipelineStage.id == target_stage_id).first()
                     if stage:
                         lead.pipeline_id = stage.pipeline_id
                db.add(lead)
                db.commit()
                db.refresh(lead)
                logger.info(f"[LeadTool] Created new lead ID {lead.id}")

            if not lead:
                return "Erro: Não foi possível criar ou localizar o lead."

            # Update Info
            if name:
                lead.name = name
                # Update contact too if exists
                contact = db.query(Contact).filter(Contact.company_id==company_id, Contact.phone==current_phone).first()
                if contact:
                    contact.name = name
                if target_stage_id:
                     # Check if stage exists and get pipeline_id
                     stage = db.query(PipelineStage).filter(PipelineStage.id == target_stage_id).first()
                     if stage:
                         lead.current_stage_id = target_stage_id
                         lead.pipeline_id = stage.pipeline_id
                         lead.last_stage_move_at = func.now()
                         logger.info(f"[LeadTool] Moved existing lead {lead.id} to target stage {target_stage_id}")

                db.add(lead)

            # Update Stage
            if action == "update_stage" or (action == "create" and stage_name):
                # Resolve Stage ID
                stage_id = None

                # 1. Try Target Stage ID from config if stage_name is "conversion" or empty
                if not stage_name and target_stage_id:
                     stage_id = target_stage_id

                # 2. Fuzzy match stage name
                if stage_name:
                    # Search stages in company's pipelines
                    # Join Pipeline to filter by company
                    stages = db.query(PipelineStage).join(Pipeline).filter(
                        Pipeline.company_id == company_id
                    ).all()

                    # Simple fuzzy matching
                    stage_name_lower = stage_name.lower()
                    best_match = None
                    for stage in stages:
                        if stage.name.lower() == stage_name_lower:
                            best_match = stage
                            break
                        if stage_name_lower in stage.name.lower(): # partial match
                            best_match = stage

                    if best_match:
                         stage_id = best_match.id
                         lead.pipeline_id = best_match.pipeline_id

                if stage_id:
                    lead.current_stage_id = stage_id
                    from datetime import datetime
                    lead.last_stage_move_at = datetime.now()
                    logger.info(f"[LeadTool] Moved lead {lead.id} to stage {stage_id}")
                else:
                    logger.warning(f"[LeadTool] Stage '{stage_name}' not found.")

            db.commit()
            return "Lead atualizado com sucesso."

        except Exception as e:
            logger.error(f"[LeadTool] Error: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return "Erro ao processar dados do lead."

    return [manage_lead_lifecycle]
