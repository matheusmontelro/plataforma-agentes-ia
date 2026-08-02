from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text
import json
import logging

from ...db import get_db
from ...models import Client, Company, User, AIResponseWindows, CalendarIntegration, AgentConfiguration, ClientCompany, BusinessType
from ...auth import hash_password
import secrets
from .models import CompleteCompanySetup, CompanySetupResponse, CompanySetupError, DaySchedule
from .security import full_security_check
import base64
import os

from backend.runtime_settings import COMPANY_LOGO_DIR, PUBLIC_BASE_URL

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/complete-clinic", response_model=CompanySetupResponse, deprecated=True)
@router.post("/complete-company", response_model=CompanySetupResponse)
async def create_complete_company(
    setup_data: CompleteCompanySetup,
    db: Session = Depends(get_db),
    _: bool = Depends(full_security_check)
):
    """
    Endpoint unificado para criar uma empresa completa com todas as configurações.

    Esta rota executa as seguintes operações em uma única transação:
    1. Cria a empresa
    2. Cria o usuário master (Client)
    3. Configura a janela de resposta da IA
    4. Configura a integração com Google Calendar
    5. Configura o prompt do assistente

    Em caso de erro, todas as operações são revertidas (rollback).
    """

    # Log da requisição recebida
    logger.info(f"Recebendo requisição de setup completo para email: {setup_data.user.email}")
    logger.info(f"Empresa: {setup_data.company.name} - CNPJ: {setup_data.company.cnpj}")
    logger.info(f"Nome customizado: {setup_data.company.name_company if setup_data.company.name_company else 'Não fornecido'}")
    logger.info(f"Logo incluído: {'Sim' if setup_data.company.logo_base64 else 'Não'}")

    # Inicia uma transação
    try:
        from ...services.company_access_control import (
            AccountEmailCollisionError,
            lock_and_validate_account_email_available,
        )
        try:
            normalized_email = lock_and_validate_account_email_available(
                db,
                str(setup_data.user.email),
            )
        except AccountEmailCollisionError as exc:
            raise HTTPException(status_code=409, detail="Email já cadastrado") from exc
        # 1.5. Validar business_type_id
        business_type = db.query(BusinessType).filter(
            BusinessType.id == setup_data.company.business_type_id
        ).first()

        if not business_type:
            logger.warning(f"Business type ID {setup_data.company.business_type_id} não encontrado, usando padrão (1)")
            # Usa o padrão business_company se o ID não existir
            setup_data.company.business_type_id = 1
            business_type = db.query(BusinessType).filter(BusinessType.id == 1).first()

        logger.info(f"Tipo de negócio: {business_type.name} (ID: {business_type.id})")

        # 2. Criar a empresa
        company = Company(
            name=setup_data.company.name,
            cnpj=setup_data.company.cnpj,
            name_company=setup_data.company.name_company if setup_data.company.name_company else setup_data.company.name,
            business_type_id=setup_data.company.business_type_id
        )
        db.add(company)
        db.flush()  # Flush para obter o ID sem fazer commit

        logger.info(f"Empresa criada: {company.id} - {company.name} (Tipo: {business_type.name})")

        # 2.1. Processar logo se fornecido
        if setup_data.company.logo_base64:
            try:
                # Decodificar base64
                logo_data = base64.b64decode(setup_data.company.logo_base64)

                # Criar diretório se não existir
                logo_dir = COMPANY_LOGO_DIR
                logo_dir.mkdir(parents=True, exist_ok=True)

                # Salvar arquivo
                filename = f"company_{company.id}_logo.png"
                filepath = logo_dir / filename

                with open(filepath, "wb") as f:
                    f.write(logo_data)

                # Atualizar URL do logo
                company.logo_url = f"{PUBLIC_BASE_URL}/media/logos/{filename}"
                db.flush()

                logger.info(f"Logo salvo: {company.logo_url}")
            except Exception as e:
                logger.warning(f"Erro ao processar logo: {str(e)}. Continuando sem logo.")
                # Não falhar toda a operação por causa do logo

        # 3. Criar o usuário master (Client)
        hashed_password = hash_password(setup_data.user.password)
        api_key = secrets.token_urlsafe(32)  # Gerar API key

        client = Client(
            email=normalized_email,
            password=hashed_password,
            company_id=company.id,
            ownership_company_id=company.id,
            api_key=api_key  # Adicionar API key
        )
        db.add(client)
        db.flush()

        logger.info(f"Cliente master criado: {client.id} - {client.email}")
        logger.info("API Key gerada para o novo cliente")

        # 3.1. Criar associação na tabela client_companies
        client_company_assoc = ClientCompany(
            client_id=client.id,
            company_id=company.id
        )
        db.add(client_company_assoc)
        db.flush()

        logger.info(f"Associação client_companies criada: client_id={client.id}, company_id={company.id}")

        # 4. Configurar janela de resposta da IA (24 horas por padrão)
        if setup_data.ai_window:
            # Configurar para 24 horas - todos os períodos habilitados
            time_windows_dict = {}
            days = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]

            for day in days:
                time_windows_dict[day] = {
                    "morning": {
                        "enabled": True,
                        "start": "00:00",
                        "end": "06:00"
                    },
                    "afternoon": {
                        "enabled": True,
                        "start": "06:00",
                        "end": "12:00"
                    },
                    "night": {
                        "enabled": True,
                        "start": "12:00",
                        "end": "18:00"
                    },
                    "dawn": {
                        "enabled": True,
                        "start": "18:00",
                        "end": "23:59"
                    }
                }

            time_windows_json = json.dumps(time_windows_dict)

            # Usar SQL direto como no ai_windows.py original
            query = text("""
                INSERT INTO ai_response_windows (company_id, timezone, time_windows, created_at, updated_at)
                VALUES (:company_id, :timezone, CAST(:time_windows AS jsonb), CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                RETURNING id
            """)

            result = db.execute(query, {
                'company_id': company.id,
                'timezone': setup_data.ai_window.timezone,
                'time_windows': time_windows_json
            })
            ai_window_id = result.scalar()

            logger.info(f"Janela de resposta IA configurada: {ai_window_id}")

        # 5. Configurar Google Calendar
        logger.info(f"Configurando Google Calendar: {setup_data.google_calendar.calendar_id}")
        calendar_integration = CalendarIntegration(
            company_id=company.id,
            provider='google',
            google_calendar_id=setup_data.google_calendar.calendar_id
        )
        db.add(calendar_integration)
        db.flush()

        logger.info(f"Google Calendar configurado com sucesso - ID: {calendar_integration.id}")

        # 6. Configurar prompt do assistente
        # Montar a estrutura completa do agent_config exatamente como o frontend espera

        pc = setup_data.prompt_config

        # Montar scheduling_config com os dias da semana
        scheduling_config = {
            "monday": pc.scheduling_config_monday.model_dump() if pc.scheduling_config_monday else DaySchedule().model_dump(),
            "tuesday": pc.scheduling_config_tuesday.model_dump() if pc.scheduling_config_tuesday else DaySchedule().model_dump(),
            "wednesday": pc.scheduling_config_wednesday.model_dump() if pc.scheduling_config_wednesday else DaySchedule().model_dump(),
            "thursday": pc.scheduling_config_thursday.model_dump() if pc.scheduling_config_thursday else DaySchedule().model_dump(),
            "friday": pc.scheduling_config_friday.model_dump() if pc.scheduling_config_friday else DaySchedule().model_dump(),
            "saturday": pc.scheduling_config_saturday.model_dump() if pc.scheduling_config_saturday else DaySchedule(afternoonEnabled=False).model_dump(),
            "sunday": pc.scheduling_config_sunday.model_dump() if pc.scheduling_config_sunday else DaySchedule(open=False, morningEnabled=False, afternoonEnabled=False).model_dump(),
            "consultation_duration": pc.consultation_duration,
            "number_of_suggestions": pc.number_of_suggestions
        }

        agent_config = AgentConfiguration(
            company_id=company.id,
            assistant_identity={
                "assistant_name": pc.assistant_name,
                "assistant_role": pc.assistant_role,
                "assistant_responsibility": pc.assistant_responsibility,
                "assistant_formality": pc.assistant_formality,
                "assistant_tone": pc.assistant_tone,
                "assistant_language": pc.assistant_language
            },
            assistant_tone_and_voice={},  # Vazio por enquanto, não usado no frontend
            company_info={
                "company_name": pc.company_name,
                "company_location": pc.company_location,
                "company_address": pc.company_address,
                "company_phone_fixed": pc.company_phone_fixed or "",
                "company_whatsapp": pc.company_whatsapp,
                "company_maps": pc.company_maps or "",
                "company_instagram": pc.company_instagram or "",
                "company_facebook": pc.company_facebook or "",
                "company_site": pc.company_site or "",
                "company_history": pc.company_history or ""
            },
            team_and_specialties={
                "technical_responsible": pc.technical_responsible,
                "treatments": [t.model_dump() for t in pc.treatments]
            },
            scheduling_config=scheduling_config,
            financial_config={
                "accepts_health_insurance": pc.accepts_health_insurance,
                "health_insurance_plans": pc.health_insurance_plans or "",
                "payment_methods": pc.payment_methods,
                "installment_conditions": pc.installment_conditions or "",
                "evaluation_price": pc.evaluation_price or "",
                "treatment_prices": pc.treatment_prices or ""
            },
            conversation_flow={
                "step0": pc.step0,
                "step1First": pc.step1First or "",
                "step1Second": pc.step1Second or "",
                "step2": pc.step2 or "",
                "step3": pc.step3 or "",
                "max_tokens": pc.max_tokens,
                "financial_redirect": {"type": pc.financial_redirect_type, "number": pc.financial_redirect_number or ""},
                "regular_redirect": {"type": pc.regular_redirect_type, "number": pc.regular_redirect_number or ""},
                "maintenance_redirect": {"type": pc.maintenance_redirect_type, "number": pc.maintenance_redirect_number or ""},
                "active_customers_redirect": {"type": pc.active_customers_redirect_type, "number": pc.active_customers_redirect_number or ""},
                "few_shots": pc.few_shots
            }
        )
        db.add(agent_config)
        db.flush()

        logger.info(f"Configuração do agente criada - ID: {agent_config.id}")
        logger.info(f"Assistente: {pc.assistant_name} - Responsável: {pc.technical_responsible}")

        # 7. Fazer commit de todas as operações
        db.commit()

        logger.info(f"Transação completada com sucesso! Todos os dados foram persistidos.")

        # 8. Preparar resposta de sucesso
        response_data = {
            "company_id": company.id,
            "user_id": client.id,
            "email": client.email,
            "configurations": {
                "company": "created",
                "user": "created",
                "ai_window": "configured" if setup_data.ai_window else "skipped",
                "google_calendar": "configured",
                "prompt": "configured"
            }
        }

        # 7.1 Criar pipeline padrão
        # (Importação interna para evitar ciclos se houver, embora models estejam no mesmo nível)
        from ....services.pipeline_service import PipelineService
        try:
             PipelineService.create_minimal_pipeline_for_company(company.id, db)
             logger.info(f"Pipeline padrão criado para a empresa {company.id}")
        except Exception as e:
             logger.error(f"Erro ao criar pipeline para empresa {company.id}: {str(e)}")
             # Não falhar o setup por isso


        logger.info(f"Setup completo realizado com sucesso para empresa {company.id}")

        return CompanySetupResponse(
            success=True,
            data=response_data,
            message=f"Empresa '{company.name}' configurada com sucesso!"
        )

    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Erro ao criar empresa completa: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Erro ao configurar empresa: {str(e)}"
        )
