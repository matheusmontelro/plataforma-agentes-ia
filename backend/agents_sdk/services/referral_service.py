"""
Referral Service - Sistema de Campanhas de Indicação
Integrado com OpenAI Agents SDK e estrutura de mensagens agendadas existente
"""

import logging
import re
import os
import base64
from typing import Optional, List, Tuple, Dict, Any
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import text
from pydantic import BaseModel

# Imports do sistema existente
from backend.models import (
    Contact,
    ContactTask,
    Lead,
    ReferralCampaign,
    ScheduledMessageExecution,
)
from backend.services.ai_provider_service import (
    AIProviderCredentialError,
    build_company_openai_run_config,
    get_company_openai_api_key,
    openai_run_trace,
)
# Import removido - agora usando apply_async() direto da task

logger = logging.getLogger(__name__)

# Configuração de áudio para mensagens de indicação
USE_AUDIO_FOR_REFERRER = os.getenv('USE_AUDIO_FOR_REFERRER', 'true').lower() == 'true'  # Para quem indica
USE_AUDIO_FOR_REFEREE = os.getenv('USE_AUDIO_FOR_REFEREE', 'true').lower() == 'true'   # Para indicados
AUDIO_VOICE = os.getenv('REFERRAL_AUDIO_VOICE', 'nova')  # Voz padrão para indicações
AUDIO_SPEED = float(os.getenv('REFERRAL_AUDIO_SPEED', '0.95'))  # Velocidade da fala


class ReferralData(BaseModel):
    """Estrutura de dados para indicações processadas"""
    names: List[str]
    phones: List[str]
    formatted_phones: List[str]
    valid_count: int = 0


class ReferralService:
    """
    Service para gerenciar campanhas de indicação

    Funcionalidades:
    - Verificar se empresa tem campanha ativa
    - Agendar solicitação de indicações (via sistema existente)
    - Processar respostas com indicações
    - Criar leads para indicados
    - Agendar mensagens de boas-vindas para indicados
    """

    def __init__(self, db: Session):
        self.db = db

    def _schedule_durable_message(
        self,
        *,
        company_id: int,
        contact: Contact,
        contact_name: str,
        message_content: str,
        message_type: str,
        scheduled_for: datetime,
        source: str,
        referrer_name: Optional[str] = None,
    ) -> bool:
        """Persist referral delivery before publishing broker work."""
        from backend.services.company_access_control import (
            enqueue_company_job_if_active,
            fence_company_job_mutation,
        )
        from backend.worker.tasks_scheduled_messages import enviar_mensagem_agendada

        fence_company_job_mutation(self.db, company_id)
        task = ContactTask(
            contact_id=contact.id,
            company_id=company_id,
            created_by=None,
            assigned_to=None,
            task_type="scheduled_message",
            title="Mensagem de indicação agendada",
            description=f"Envio automático para {contact_name}",
            message_content=message_content,
            message_type=message_type,
            scheduled_for=scheduled_for,
            reminder_minutes=0,
            status="pending",
            priority="medium",
            tags=["agents_sdk", "referral"],
            task_metadata={
                "source": source,
                "referrer_name": referrer_name,
            },
        )
        self.db.add(task)
        self.db.flush()
        execution = ScheduledMessageExecution(
            task_id=task.id,
            contact_id=contact.id,
            company_id=company_id,
            message_type=message_type,
            message_content=message_content,
            message_file_path=None,
            status="SCHEDULED",
            scheduled_for=scheduled_for,
        )
        self.db.add(execution)
        self.db.commit()

        def is_still_pending() -> bool:
            task_pending = (
                self.db.query(ContactTask.id)
                .filter(
                    ContactTask.id == task.id,
                    ContactTask.status == "pending",
                )
                .first()
                is not None
            )
            execution_pending = (
                self.db.query(ScheduledMessageExecution.id)
                .filter(
                    ScheduledMessageExecution.task_id == task.id,
                    ScheduledMessageExecution.status == "SCHEDULED",
                )
                .first()
                is not None
            )
            return task_pending and execution_pending

        queued, _ = enqueue_company_job_if_active(
            self.db,
            company_id,
            is_still_pending=is_still_pending,
            enqueue=lambda: enviar_mensagem_agendada.apply_async(
                args=[task.id],
                eta=scheduled_for,
                queue="scheduled_messages_queue",
            ),
        )
        return queued

    def _convert_text_to_audio(
        self,
        text: str,
        company_id: int,
        max_length: int = 1500,
    ) -> Optional[str]:
        """
        Converte texto em áudio usando OpenAI TTS

        Args:
            text: Texto para converter
            max_length: Tamanho máximo do texto

        Returns:
            Base64 do áudio ou None se falhar
        """
        try:
            try:
                api_key = get_company_openai_api_key(
                    self.db,
                    company_id,
                )
            except AIProviderCredentialError:
                logger.warning(
                    "[ReferralService] Chave OpenAI da empresa não configurada; enviando como texto company_id=%s",
                    company_id,
                )
                return None

            # Limitar tamanho do texto
            audio_text = text[:max_length]

            # Gerar áudio com OpenAI
            import openai
            client = openai.OpenAI(api_key=api_key)

            logger.info(f"[ReferralService] Gerando áudio: {len(audio_text)} caracteres, voz: {AUDIO_VOICE}")

            response = client.audio.speech.create(
                model="tts-1",  # Modelo mais rápido e econômico
                voice=AUDIO_VOICE,
                input=audio_text,
                speed=AUDIO_SPEED
            )

            # Converter para base64
            audio_base64 = base64.b64encode(response.content).decode('utf-8')

            logger.info(f"[ReferralService] Áudio gerado com sucesso: {len(response.content)} bytes")
            return audio_base64

        except Exception as e:
            logger.error(
                "[ReferralService] Erro ao gerar áudio: %s",
                type(e).__name__,
            )
            return None

    def get_active_campaign(self, company_id: int) -> Optional[ReferralCampaign]:
        """
        Busca campanha ativa da empresa

        Args:
            company_id: ID da empresa

        Returns:
            ReferralCampaign se ativa, None caso contrário
        """
        try:
            campaign = self.db.query(ReferralCampaign).filter(
                ReferralCampaign.company_id == company_id,
                ReferralCampaign.active == True
            ).first()

            if campaign:
                logger.info(f"[ReferralService] Campanha ativa encontrada para empresa {company_id}: {campaign.campaign_name}")
            else:
                logger.info(f"[ReferralService] Nenhuma campanha ativa para empresa {company_id}")

            return campaign

        except Exception as e:
            logger.error(f"[ReferralService] Erro ao buscar campanha para empresa {company_id}: {e}")
            return None

    def schedule_referrer_request(
        self,
        company_id: int,
        phone: str,
        customer_name: str,
        campaign: ReferralCampaign
    ) -> bool:
        """
        Agenda mensagem de solicitação de indicações usando sistema existente

        Args:
            company_id: ID da empresa
            phone: Telefone do indicador
            customer_name: Nome do cliente que vai indicar
            campaign: Dados da campanha

        Returns:
            True se agendado com sucesso, False caso contrário
        """
        try:
            logger.info(f"[ReferralService] Agendando solicitação de indicações para {phone} (empresa {company_id})")

            # Buscar contact_id
            contact = self.db.query(Contact).filter(
                Contact.phone == phone,
                Contact.company_id == company_id
            ).first()

            if not contact:
                logger.warning(f"[ReferralService] Contato não encontrado para {phone} na empresa {company_id}")
                return False

            # Calcular horário de envio
            scheduled_for = datetime.utcnow() + timedelta(minutes=campaign.delay_minutes)

            # NOVO: Gerar mensagem com agent AGORA (na hora do agendamento)
            try:
                generated_message = self._generate_message_sync(
                    customer_name=customer_name,
                    company_id=company_id,
                    campaign=campaign
                )
            except Exception as e:
                logger.error(f"[ReferralService] Erro ao gerar mensagem: {e}")
                generated_message = campaign.referrer_campaign_description or "Mensagem padrão de indicação"

            # Decidir se envia áudio ou texto
            message_type = 'text'
            message_content = generated_message

            if USE_AUDIO_FOR_REFERRER:
                logger.info(f"[ReferralService] Convertendo mensagem do indicador para áudio")
                audio_base64 = self._convert_text_to_audio(
                    generated_message,
                    company_id,
                )

                if audio_base64:
                    message_content = audio_base64
                    message_type = 'audio'
                    logger.info(f"[ReferralService] Mensagem será enviada como ÁUDIO para {customer_name}")
                else:
                    logger.warning(f"[ReferralService] Falha na conversão, enviando como TEXTO")

            if not self._schedule_durable_message(
                company_id=company_id,
                contact=contact,
                contact_name=customer_name,
                message_content=message_content,
                message_type=message_type,
                scheduled_for=scheduled_for,
                source="referral_request",
            ):
                logger.info(
                    "[ReferralService] Solicitação não enfileirada porque o acesso foi suspenso"
                )
                return False

            logger.info(f"[ReferralService] ✅ Solicitação agendada para {scheduled_for}")
            return True

        except Exception as e:
            logger.error(f"[ReferralService] Erro ao agendar solicitação para {phone}: {e}")
            self.db.rollback()
            return False

    def parse_referral_text(self, referral_text: str) -> ReferralData:
        """
        Parse do texto com indicações enviado pelo usuário

        Formatos aceitos:
        - "Nome - Telefone"
        - "Nome: Telefone"
        - "Nome (telefone)"
        - "Nome telefone"

        Args:
            referral_text: Texto com as indicações

        Returns:
            ReferralData com dados processados
        """
        try:
            logger.info(f"[ReferralService] Processando texto de indicações: {referral_text[:100]}...")

            names = []
            phones = []
            formatted_phones = []

            # Padrões regex para diferentes formatos
            patterns = [
                r'([A-Za-zÀ-ÿ\s]+?)\s*[-:]\s*(\(?[\d\s\(\)\-\+]+\)?)',  # Nome - Telefone ou Nome: Telefone
                r'([A-Za-zÀ-ÿ\s]+?)\s*\(\s*(\(?[\d\s\(\)\-\+]+\)?)\s*\)', # Nome (Telefone)
                r'([A-Za-zÀ-ÿ\s]{2,})\s+(\(?[\d\s\(\)\-\+]{8,}\)?)',       # Nome Telefone (espaçado)
            ]

            lines = referral_text.strip().split('\n')

            for line in lines:
                line = line.strip()
                if not line:
                    continue

                matched = False
                for pattern in patterns:
                    matches = re.findall(pattern, line)
                    for match in matches:
                        name = match[0].strip()
                        phone = match[1].strip()

                        # Validar nome (pelo menos 2 palavras)
                        if len(name.split()) < 2:
                            continue

                        # Limpar e formatar telefone
                        formatted_phone = self._format_phone(phone)
                        if formatted_phone:
                            names.append(name)
                            phones.append(phone)
                            formatted_phones.append(formatted_phone)
                            matched = True
                            logger.debug(f"[ReferralService] Indicação válida: {name} - {formatted_phone}")

                if not matched:
                    logger.debug(f"[ReferralService] Linha não reconhecida: {line}")

            result = ReferralData(
                names=names,
                phones=phones,
                formatted_phones=formatted_phones,
                valid_count=len(names)
            )

            logger.info(f"[ReferralService] ✅ Processadas {result.valid_count} indicações válidas")
            return result

        except Exception as e:
            logger.error(f"[ReferralService] Erro ao processar indicações: {e}")
            return ReferralData(names=[], phones=[], formatted_phones=[], valid_count=0)

    def _format_phone(self, phone: str) -> Optional[str]:
        """
        Formata telefone para padrão 55ddd912345678

        Args:
            phone: Telefone em qualquer formato

        Returns:
            Telefone formatado ou None se inválido
        """
        try:
            # Remover caracteres não numéricos
            digits = re.sub(r'\D', '', phone)

            # Validar comprimento básico
            if len(digits) < 10 or len(digits) > 13:
                return None

            # Aplicar lógica de formatação
            if len(digits) == 11:  # ddd + 9 dígitos
                return f"55{digits}"
            elif len(digits) == 10:  # ddd + 8 dígitos (adicionar 9)
                return f"55{digits[:2]}9{digits[2:]}"
            elif len(digits) == 12 and digits.startswith('55'):  # já tem 55
                return digits
            elif len(digits) == 13 and digits.startswith('55'):  # já formatado
                return digits
            else:
                return None

        except Exception as e:
            logger.warning(f"[ReferralService] Erro ao formatar telefone {phone}: {e}")
            return None

    def create_referral_leads(
        self,
        company_id: int,
        referrer_phone: str,
        referral_data: ReferralData,
        campaign: ReferralCampaign
    ) -> int:
        """
        Cria leads para as indicações e agenda mensagens de boas-vindas

        Args:
            company_id: ID da empresa
            referrer_phone: Telefone de quem indicou
            referral_data: Dados das indicações processadas
            campaign: Dados da campanha

        Returns:
            Número de leads criados com sucesso
        """
        try:
            logger.info(f"[ReferralService] Criando {referral_data.valid_count} leads para empresa {company_id}")

            created_count = 0
            referrer_name = self._get_customer_name(referrer_phone, company_id)

            # Buscar client_id da empresa
            client_id = self._get_client_id(company_id)
            if not client_id:
                logger.error(f"[ReferralService] Client não encontrado para empresa {company_id}")
                return 0

            for i in range(referral_data.valid_count):
                name = referral_data.names[i]
                formatted_phone = referral_data.formatted_phones[i]

                try:
                    # Buscar follow_up_sequence_id da empresa para ativar follow-up automaticamente
                    follow_up_seq = self.db.execute(text("""
                        SELECT id FROM follow_up_sequences
                        WHERE company_id = :company_id AND client_id = :client_id
                        ORDER BY id LIMIT 1
                    """), {
                        "company_id": company_id,
                        "client_id": client_id
                    }).fetchone()

                    sequence_id = follow_up_seq.id if follow_up_seq else None
                    if sequence_id:
                        logger.info(f"[ReferralService] Follow-up sequence encontrada: {sequence_id}")

                    # Verificar se lead já existe (APENAS UMA VEZ)
                    existing_lead = self.db.execute(text("""
                        SELECT id, name, follow_up_sequence_id FROM leads
                        WHERE phone = :phone AND company_id = :company_id
                        LIMIT 1
                    """), {"phone": formatted_phone, "company_id": company_id}).fetchone()

                    if existing_lead:
                        # Lead existe - atualizar se necessário
                        updates_needed = []
                        params = {"lead_id": existing_lead.id}

                        # Atualizar nome se o novo for mais completo
                        if name and len(name.split()) > len((existing_lead.name or "").split()):
                            updates_needed.append("name = :name")
                            params["name"] = name
                            logger.info(f"[ReferralService] Atualizando nome do lead {formatted_phone}: {name}")

                        # CORREÇÃO: Atribuir sequence_id se não tiver
                        if sequence_id and not existing_lead.follow_up_sequence_id:
                            updates_needed.append("follow_up_sequence_id = :seq_id")
                            params["seq_id"] = sequence_id
                            logger.info(f"[ReferralService] Atribuindo follow-up sequence {sequence_id} ao lead existente {formatted_phone}")

                        if updates_needed:
                            update_query = f"UPDATE leads SET {', '.join(updates_needed)} WHERE id = :lead_id"
                            self.db.execute(text(update_query), params)
                            self.db.commit()

                        # CORREÇÃO: Se acabamos de atribuir sequence, agendar primeiro step
                        if sequence_id and not existing_lead.follow_up_sequence_id:
                            lead_id = existing_lead.id

                            # Agendar primeiro step do follow-up
                            try:
                                first_step = self.db.execute(text("""
                                    SELECT id, send_after, send_after_unit, step_number
                                    FROM follow_up_steps
                                    WHERE follow_up_sequence_id = :seq_id
                                    AND step_number = 1
                                    LIMIT 1
                                """), {"seq_id": sequence_id}).fetchone()

                                if first_step:
                                    # Calcular delay baseado na unidade
                                    if first_step.send_after_unit == 'minutes':
                                        delay = timedelta(minutes=first_step.send_after)
                                    elif first_step.send_after_unit == 'hours':
                                        delay = timedelta(hours=first_step.send_after)
                                    elif first_step.send_after_unit == 'days':
                                        delay = timedelta(days=first_step.send_after)
                                    else:
                                        delay = timedelta(hours=1)  # Default 1 hora

                                    eta = datetime.utcnow() + delay
                                    logger.info(f"[ReferralService] Agendando follow-up step 1 para lead existente {name} às {eta}")

                                    # Criar registro de execução do follow-up
                                    self.db.execute(text("""
                                        INSERT INTO follow_up_executions
                                            (lead_id, company_id, follow_up_sequence_id, follow_up_step_id,
                                             step_number, status, scheduled_for)
                                        VALUES
                                            (:lead_id, :company_id, :seq_id, :step_id,
                                             :step_number, 'SCHEDULED', :scheduled_for)
                                        ON CONFLICT (lead_id, follow_up_sequence_id, follow_up_step_id)
                                        DO UPDATE SET
                                            status = 'SCHEDULED',
                                            scheduled_for = EXCLUDED.scheduled_for,
                                            updated_at = now()
                                    """), {
                                        "lead_id": lead_id,
                                        "company_id": company_id,
                                        "seq_id": sequence_id,
                                        "step_id": first_step.id,
                                        "step_number": 1,
                                        "scheduled_for": eta
                                    })
                                    self.db.commit()

                                    # Agendar task de follow-up
                                    from backend.services.company_access_control import capture_company_job_epoch
                                    from backend.worker.tasks import enviar_passo_followup

                                    operational_epoch = capture_company_job_epoch(
                                        self.db,
                                        company_id,
                                    )
                                    enviar_passo_followup.apply_async(
                                        args=[
                                            lead_id,
                                            1,
                                            sequence_id,
                                            sequence_id,
                                            operational_epoch,
                                        ],
                                        eta=eta
                                    )
                                    self.db.commit()

                                    logger.info(f"[ReferralService] ✅ Follow-up agendado para lead existente {name}")

                            except Exception as e:
                                logger.error(f"[ReferralService] Erro ao agendar follow-up para lead existente: {e}")

                        continue  # Pular para próxima indicação

                    # Criar novo lead com source "Indicação" e follow_up_sequence_id
                    new_lead = Lead(
                        client_id=client_id,
                        company_id=company_id,
                        name=name,
                        phone=formatted_phone,
                        source_id="Indicação",
                        created_at=datetime.utcnow(),
                        data_entrada=datetime.utcnow(),
                        follow_up_sequence_id=sequence_id  # Adicionar sequence_id para ativar follow-up
                    )

                    self.db.add(new_lead)
                    self.db.flush()  # Para pegar o ID

                    # Se tiver follow_up_sequence_id, agendar primeiro passo do follow-up
                    if sequence_id:
                        try:
                            first_step = self.db.execute(text("""
                                SELECT id, send_after, send_after_unit, step_number
                                FROM follow_up_steps
                                WHERE follow_up_sequence_id = :seq_id
                                AND step_number = 1
                                LIMIT 1
                            """), {"seq_id": sequence_id}).fetchone()

                            if first_step:
                                # Calcular delay baseado na unidade
                                if first_step.send_after_unit == 'minutes':
                                    delay = timedelta(minutes=first_step.send_after)
                                elif first_step.send_after_unit == 'hours':
                                    delay = timedelta(hours=first_step.send_after)
                                elif first_step.send_after_unit == 'days':
                                    delay = timedelta(days=first_step.send_after)
                                else:
                                    delay = timedelta(hours=1)  # Default 1 hora

                                eta = datetime.utcnow() + delay
                                logger.info(f"[ReferralService] Agendando follow-up step 1 para novo lead {name} às {eta}")

                                # Criar registro de execução do follow-up
                                self.db.execute(text("""
                                    INSERT INTO follow_up_executions
                                        (lead_id, company_id, follow_up_sequence_id, follow_up_step_id,
                                         step_number, status, scheduled_for)
                                    VALUES
                                        (:lead_id, :company_id, :seq_id, :step_id,
                                         :step_number, 'SCHEDULED', :scheduled_for)
                                    ON CONFLICT (lead_id, follow_up_sequence_id, follow_up_step_id)
                                    DO UPDATE SET
                                        status = 'SCHEDULED',
                                        scheduled_for = EXCLUDED.scheduled_for,
                                        updated_at = now()
                                """), {
                                    "lead_id": new_lead.id,
                                    "company_id": company_id,
                                    "seq_id": sequence_id,
                                    "step_id": first_step.id,
                                    "step_number": 1,
                                    "scheduled_for": eta
                                })
                                self.db.commit()

                                # Agendar task de follow-up
                                from backend.services.company_access_control import capture_company_job_epoch
                                from backend.worker.tasks import enviar_passo_followup

                                operational_epoch = capture_company_job_epoch(
                                    self.db,
                                    company_id,
                                )
                                enviar_passo_followup.apply_async(
                                    args=[
                                        new_lead.id,
                                        1,
                                        sequence_id,
                                        sequence_id,
                                        operational_epoch,
                                    ],
                                    eta=eta
                                )
                                self.db.commit()

                                logger.info(f"[ReferralService] ✅ Follow-up agendado para novo lead {name}")

                        except Exception as e:
                            logger.error(f"[ReferralService] Erro ao agendar follow-up para novo lead: {e}")

                    # Agendar mensagem de boas-vindas para indicado
                    if campaign.contact_referees_immediately:
                        self._schedule_referee_welcome(
                            company_id=company_id,
                            referee_phone=formatted_phone,
                            referee_name=name,
                            referrer_name=referrer_name,
                            campaign=campaign
                        )

                    created_count += 1
                    logger.info(f"[ReferralService] ✅ Lead criado: {name} ({formatted_phone})")

                except Exception as e:
                    logger.error(f"[ReferralService] Erro ao criar lead {name}: {e}")
                    continue

            self.db.commit()

            logger.info(f"[ReferralService] ✅ {created_count} leads criados com sucesso")
            return created_count

        except Exception as e:
            logger.error(f"[ReferralService] Erro ao criar leads: {e}")
            self.db.rollback()
            return 0

    def _schedule_referee_welcome(
        self,
        company_id: int,
        referee_phone: str,
        referee_name: str,
        referrer_name: str,
        campaign: ReferralCampaign
    ) -> bool:
        """
        Agenda mensagem de boas-vindas para indicado
        """
        try:
            # Buscar ou criar contato para o indicado
            contact = self.db.query(Contact).filter(
                Contact.phone == referee_phone,
                Contact.company_id == company_id
            ).first()

            if not contact:
                # Criar novo contato
                contact = Contact(
                    company_id=company_id,
                    phone=referee_phone,
                    name=referee_name,
                    created_at=datetime.utcnow()
                )
                self.db.add(contact)
                self.db.flush()

            # Calcular horário de envio
            scheduled_for = datetime.utcnow() + timedelta(minutes=campaign.referee_delay_minutes)

            # Gerar mensagem com agent AGORA (mesmo padrão do schedule_referrer_request)
            try:
                generated_message = self._generate_referee_welcome_message_sync(
                    referee_name=referee_name,
                    referrer_name=referrer_name,
                    company_id=company_id,
                    campaign=campaign
                )
            except Exception as e:
                logger.error(f"[ReferralService] Erro ao gerar mensagem de boas-vindas: {e}")
                generated_message = f"Olá, {referee_name}! Você foi indicado pelo {referrer_name}. {campaign.referee_campaign_description}"

            # Decidir se envia áudio ou texto
            message_type = 'text'
            message_content = generated_message

            if USE_AUDIO_FOR_REFEREE:
                logger.info(f"[ReferralService] Convertendo boas-vindas para áudio para {referee_name}")
                audio_base64 = self._convert_text_to_audio(
                    generated_message,
                    company_id,
                )

                if audio_base64:
                    message_content = audio_base64
                    message_type = 'audio'
                    logger.info(f"[ReferralService] Boas-vindas será enviada como ÁUDIO para {referee_name}")
                else:
                    logger.warning(f"[ReferralService] Falha na conversão, enviando como TEXTO")

            if not self._schedule_durable_message(
                company_id=company_id,
                contact=contact,
                contact_name=referee_name,
                message_content=message_content,
                message_type=message_type,
                scheduled_for=scheduled_for,
                source="referral_welcome",
                referrer_name=referrer_name,
            ):
                logger.info(
                    "[ReferralService] Boas-vindas não enfileiradas porque o acesso foi suspenso"
                )
                return False

            logger.info(f"[ReferralService] ✅ Boas-vindas agendadas para {referee_name} em {scheduled_for}")
            return True

        except Exception as e:
            logger.error(f"[ReferralService] Erro ao agendar boas-vindas para {referee_name}: {e}")
            self.db.rollback()
            return False

    def _get_customer_name(self, phone: str, company_id: int) -> str:
        """Busca nome do cliente pelo telefone"""
        try:
            contact = self.db.query(Contact).filter(
                Contact.phone == phone,
                Contact.company_id == company_id
            ).first()
            return contact.name if contact else "Um amigo"
        except:
            return "Um amigo"

    def _get_client_id(self, company_id: int) -> Optional[str]:
        """Busca client_id da empresa"""
        try:
            result = self.db.execute(text("""
                SELECT id as client_id FROM clients WHERE company_id = :company_id LIMIT 1
            """), {"company_id": company_id}).fetchone()
            return str(result.client_id) if result else None
        except:
            return None

    def _get_company_name(self, company_id: int) -> str:
        """Busca nome da empresa do agent_config"""
        try:
            from backend.prompt.db_integration.agent_config import get_agent_config_dict
            agent_config = get_agent_config_dict(self.db, company_id)
            company_info = agent_config.get('company_info', {})
            return company_info.get('company_name', 'Nossa Empresa')
        except:
            return "Nossa Empresa"

    def _generate_referee_welcome_message_sync(
        self,
        referee_name: str,
        referrer_name: str,
        company_id: int,
        campaign: ReferralCampaign
    ) -> str:
        """
        Gera mensagem de boas-vindas para indicado usando agent especializado
        """
        import concurrent.futures

        def run_in_new_thread():
            import asyncio
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                return loop.run_until_complete(
                    self._generate_referee_welcome_message_async(referee_name, referrer_name, company_id, campaign)
                )
            finally:
                loop.close()
                asyncio.set_event_loop(None)

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(run_in_new_thread)
            return future.result(timeout=30)

    async def _generate_referee_welcome_message_async(
        self,
        referee_name: str,
        referrer_name: str,
        company_id: int,
        campaign: ReferralCampaign
    ) -> str:
        """
        Gera mensagem de boas-vindas usando agent especializado
        """
        try:
            from agents import Runner, trace
            from backend.agents_sdk.agents.referral_agents import referee_agent, format_referrer_prompt

            company_name = self._get_company_name(company_id)

            # Gerar prompt para agent de boas-vindas
            prompt = f"""
Gere uma mensagem de boas-vindas para pessoa indicada:

DADOS:
- Indicado: {referee_name}
- Indicador: {referrer_name}
- Empresa: {company_name}
- Benefício: {campaign.referee_campaign_description}

INSTRUÇÕES:
{campaign.referee_campaign_instructions or 'Seja acolhedor e convide para agendar'}

Gere mensagem acolhedora e personalizada:
"""

            run_config = build_company_openai_run_config(
                self.db,
                company_id,
                tracing_disabled=True,
            )
            with openai_run_trace(
                run_config,
                workflow_name="referee_welcome_message_generation",
            ):
                result = await Runner.run(
                    referee_agent,
                    prompt,
                    run_config=run_config,
                )
                generated_message = result.final_output

            logger.info(f"[ReferralService] ✅ Mensagem de boas-vindas gerada: {len(generated_message)} chars")
            return generated_message

        except Exception as e:
            logger.error(f"[ReferralService] Erro ao gerar mensagem de boas-vindas: {e}")
            # Fallback simples
            return f"Olá, {referee_name}! Você foi indicado pelo {referrer_name}. {campaign.referee_campaign_description} Entre em contato para agendar!"

    def _generate_message_sync(
        self,
        customer_name: str,
        company_id: int,
        campaign: ReferralCampaign
    ) -> str:
        """
        Gera mensagem de forma síncrona, compatível com Celery workers
        Baseado no padrão do OpenAI Agents SDK para resolver event loop conflicts
        """
        import concurrent.futures
        import threading

        def run_in_new_thread():
            """Executa geração async em thread separada com seu próprio loop"""
            import asyncio
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                return loop.run_until_complete(
                    self._generate_referrer_message_async(customer_name, company_id, campaign)
                )
            finally:
                loop.close()
                asyncio.set_event_loop(None)

        # Usar ThreadPoolExecutor para evitar conflitos de event loop (padrão do OpenAI SDK)
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(run_in_new_thread)
            return future.result(timeout=30)  # timeout de 30 segundos

    async def _generate_referrer_message_async(
        self,
        customer_name: str,
        company_id: int,
        campaign: ReferralCampaign
    ) -> str:
        """
        Gera mensagem para indicador usando agent especializado
        """
        try:
            from agents import Runner, trace
            from backend.agents_sdk.agents.referral_agents import referrer_agent, format_referrer_prompt

            company_name = self._get_company_name(company_id)

            # Gerar prompt para agent
            prompt = format_referrer_prompt(
                customer_name=customer_name,
                company_name=company_name,
                campaign_description=campaign.referrer_campaign_description,
                campaign_instructions=campaign.referrer_campaign_instructions or "",
                max_referrals=campaign.max_referrals_per_request
            )

            run_config = build_company_openai_run_config(
                self.db,
                company_id,
                tracing_disabled=True,
            )
            with openai_run_trace(
                run_config,
                workflow_name="referrer_message_generation_on_schedule",
            ):
                result = await Runner.run(
                    referrer_agent,
                    prompt,
                    run_config=run_config,
                )
                generated_message = result.final_output

            logger.info(f"[ReferralService] ✅ Mensagem gerada no agendamento: {len(generated_message)} chars")
            return generated_message

        except Exception as e:
            logger.error(f"[ReferralService] Erro ao gerar mensagem: {e}")
            # Fallback simples
            return f"Olá {customer_name}! Obrigado por agendar. Que tal indicar alguns amigos? Envie: Nome - Telefone"
