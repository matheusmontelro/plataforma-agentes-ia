# State Triggers for Automatic Function Calling
import logging
from typing import Optional
from openai import OpenAI
from ..config.company_context import CompanyContext
from .validation_guards import StateValidationGuards, SecurityGuards

logger = logging.getLogger(__name__)


class StateTriggerHandler:
    """
    Gerencia triggers automáticos baseados no estado da conversa.
    Substitui instruções "amadoras" no prompt por lógica robusta.
    """

    @staticmethod
    def _openai_client(openai_api_key: str) -> OpenAI:
        """Create a client only from an explicit company-scoped credential."""

        api_key = (openai_api_key or "").strip()
        if not api_key:
            raise ValueError(
                "Chave OpenAI explícita da empresa é obrigatória"
            )
        return OpenAI(api_key=api_key)

    @staticmethod
    async def handle_post_message_processing(
        wrapper,
        user_message: str,
        agent_response: str,
        openai_api_key: str,
    ) -> Optional[str]:
        """
        Processa triggers após uma mensagem ser processada.

        Args:
            wrapper: Context wrapper do Agents SDK
            user_message: Mensagem do usuário
            agent_response: Resposta do agent (não usado atualmente)

        Returns:
            Optional[str]: Mensagem adicional se algum trigger foi executado
        """
        context = wrapper.context
        state_manager = await context.get_state_manager()

        logger.info(f"[StateTrigger] Processando triggers - step={state_manager.state.current_step}, user_msg='{user_message[:50]}...'")

        # Verifica se deve disparar agendamento automático
        should_trigger_scheduling = await state_manager.should_trigger_automatic_scheduling()
        logger.info(f"[StateTrigger] should_trigger_automatic_scheduling = {should_trigger_scheduling}")

        if should_trigger_scheduling:
            logger.info("[StateTrigger] Disparando agendamento automático")
            return await StateTriggerHandler._trigger_automatic_scheduling(wrapper)

        # Verifica se deve disparar cancelamento automático
        should_trigger_cancellation = await state_manager.should_trigger_automatic_cancellation()
        logger.info(f"[StateTrigger] should_trigger_automatic_cancellation = {should_trigger_cancellation}")

        if should_trigger_cancellation:
            logger.info("[StateTrigger] Disparando cancelamento automático")
            return await StateTriggerHandler._trigger_automatic_cancellation(wrapper)

        # Verifica se deve disparar reagendamento automático
        should_trigger_rescheduling = await state_manager.should_trigger_automatic_rescheduling()
        logger.info(f"[StateTrigger] should_trigger_automatic_rescheduling = {should_trigger_rescheduling}")

        if should_trigger_rescheduling:
            logger.info("[StateTrigger] Disparando reagendamento automático")
            return await StateTriggerHandler._trigger_automatic_rescheduling(wrapper)

        # Verifica se precisa avançar de step baseado no conteúdo
        logger.info(f"[StateTrigger] Verificando transições de step para: '{user_message}'")
        await StateTriggerHandler._check_step_transitions(
            wrapper,
            user_message,
            openai_api_key,
        )

        # Detecta preferências de agendamento para melhorar sugestões
        await StateTriggerHandler._detect_scheduling_preferences(wrapper, user_message)

        # Log final do estado após processamento
        final_state = await context.get_state_manager()
        logger.info(f"[StateTrigger] Estado final: step={final_state.state.current_step}, dados={list(final_state.state.state_data.keys())}")

        return None

    @staticmethod
    async def _trigger_automatic_scheduling(wrapper) -> str:
        """
        Dispara o agendamento automático quando todos os dados estão coletados.
        Inclui validações robustas e guard rails.
        """
        context = wrapper.context
        state_manager = await context.get_state_manager()

        try:
            # 1. Validações de segurança
            if not await SecurityGuards.validate_company_access(wrapper, "agendar_consulta"):
                SecurityGuards.log_security_event(
                    context.company_id, context.contact_phone,
                    "UNAUTHORIZED_SCHEDULING", "Access denied for automatic scheduling"
                )
                return "\n\n❌ Não foi possível processar o agendamento neste momento."

            # 2. Validação dos dados de agendamento
            data_valid, errors = await StateValidationGuards.validate_scheduling_data(wrapper)
            if not data_valid:
                logger.warning(f"[StateTrigger] Dados inválidos: {errors}")
                return f"\n\n❌ {'; '.join(errors)}"

            # 3. Verifica rate limiting
            can_proceed, rate_limit_msg = await StateValidationGuards.check_rate_limiting(wrapper)
            if not can_proceed:
                logger.warning(f"[StateTrigger] Rate limit ativo: {rate_limit_msg}")
                return f"\n\n❌ {rate_limit_msg}"

            # 4. Obtém e sanitiza dados
            raw_data = {
                "nome": state_manager.get_state_data("nome"),
                "data": state_manager.get_state_data("data"),
                "horario": state_manager.get_state_data("horario")
            }

            sanitized_data = await StateValidationGuards.sanitize_input_data(raw_data)

            if not all(sanitized_data.values()):
                logger.warning("[StateTrigger] Dados insuficientes após sanitização")
                return "\n\n❌ Dados de agendamento incompletos."

            # 5. Formata data_hora
            data_hora = f"{sanitized_data['data']} {sanitized_data['horario']}"

            logger.info(f"[StateTrigger] Executando agendamento automático: {data_hora}, {sanitized_data['nome']}")

            # 6. Chama a função de agendamento via AppointmentService
            from ..services import AppointmentService

            appointment_service = AppointmentService(
                db=context.db,
                company_id=context.company_id
            )

            api_key = getattr(context, 'api_key', None)

            result_dict = await appointment_service.create_appointment(
                phone=context.contact_phone,
                nome=sanitized_data['nome'],
                data=sanitized_data['data'],
                horario=sanitized_data['horario'],
                api_key=api_key
            )

            # Converte resultado para string esperada
            if result_dict["success"]:
                result = result_dict["message"]
            else:
                result = f"❌ {result_dict.get('message', 'Erro no agendamento')}"

            # 7. Se sucesso, atualiza estado
            if result and not result.startswith("❌"):
                # Marca o agendamento como confirmado
                await state_manager.set_state_data("agendamento_confirmado", True)

                # Reseta estado pós-confirmação (inclui cooldown)
                await state_manager.reset_post_confirmation()

                logger.info("[StateTrigger] Agendamento automático executado com sucesso")

                # Log de segurança para auditoria
                SecurityGuards.log_security_event(
                    context.company_id, context.contact_phone,
                    "SUCCESSFUL_SCHEDULING", f"Auto-scheduled: {data_hora}"
                )

                # 🎯 RETORNA A MENSAGEM PADRÃO DO AGENDAMENTO_LOGIC
                # A função agendar_consulta já retorna a mensagem padrão gerada por _generate_confirmation_message
                return f"\n\n{result}"
            else:
                # Se falhou, mantém no step 5 para retry
                logger.error(f"[StateTrigger] Agendamento falhou: {result}")
                return f"\n\n{result}" if result else "\n\n❌ Erro no agendamento."

        except Exception as e:
            logger.error(f"[StateTrigger] Erro no agendamento automático: {e}")
            SecurityGuards.log_security_event(
                context.company_id, context.contact_phone,
                "SCHEDULING_ERROR", str(e)
            )
            return "\n\n❌ Ocorreu um erro ao processar seu agendamento. Por favor, tente novamente."

    @staticmethod
    async def _trigger_automatic_cancellation(wrapper) -> str:
        """
        Dispara o cancelamento automático quando detecta intenção.
        """
        context = wrapper.context
        state_manager = await context.get_state_manager()

        try:
            logger.info(f"[StateTrigger] Executando cancelamento automático")

            # Chama o serviço de cancelamento
            from ..services import AppointmentService

            appointment_service = AppointmentService(
                db=context.db,
                company_id=context.company_id
            )

            api_key = getattr(context, 'api_key', None)

            result_dict = await appointment_service.cancel_appointment(
                phone=context.contact_phone,
                api_key=api_key
            )

            # Marca como processado para evitar loops
            await state_manager.set_state_data("cancelamento_processado", True)

            if result_dict["success"]:
                logger.info("[StateTrigger] Cancelamento automático executado com sucesso")

                # Limpa dados de agendamento anterior
                await state_manager.set_state_data("data", None)
                await state_manager.set_state_data("horario", None)
                await state_manager.set_state_data("agendamento_confirmado", False)

                # Log de segurança para auditoria
                SecurityGuards.log_security_event(
                    context.company_id, context.contact_phone,
                    "SUCCESSFUL_CANCELLATION", "Auto-cancelled"
                )

                return f"\n\n{result_dict['message']}"
            else:
                logger.error(f"[StateTrigger] Cancelamento falhou: {result_dict.get('message')}")
                return f"\n\n{result_dict.get('message', '❌ Erro no cancelamento.')}"

        except Exception as e:
            logger.error(f"[StateTrigger] Erro no cancelamento automático: {e}")
            SecurityGuards.log_security_event(
                context.company_id, context.contact_phone,
                "CANCELLATION_ERROR", str(e)
            )
            return "\n\n❌ Ocorreu um erro ao processar seu cancelamento. Por favor, tente novamente."

    @staticmethod
    async def _trigger_automatic_rescheduling(wrapper) -> str:
        """
        Dispara o reagendamento automático quando detectado.
        """
        context = wrapper.context
        state_manager = await context.get_state_manager()

        try:
            logger.info("[StateTrigger] Executando reagendamento automático")

            # Obtém dados salvos do reagendamento
            nova_data = state_manager.get_state_data("reagendamento_data")
            novo_horario = state_manager.get_state_data("reagendamento_horario")
            nome = state_manager.get_state_data("nome")

            if not all([nova_data, novo_horario, nome]):
                logger.warning("[StateTrigger] Dados incompletos para reagendamento")
                # Não retorna mensagem de erro, deixa o fluxo normal continuar
                return None

            # Validações de segurança
            if not await SecurityGuards.validate_company_access(wrapper, "reagendar_consulta"):
                SecurityGuards.log_security_event(
                    context.company_id, context.contact_phone,
                    "UNAUTHORIZED_RESCHEDULING", "Access denied for automatic rescheduling"
                )
                return "\n\n❌ Não foi possível processar o reagendamento neste momento."

            # Usa o AppointmentService
            from ..services.appointment_service import AppointmentService

            appointment_service = AppointmentService(
                db=context.db,
                company_id=context.company_id
            )

            result_dict = await appointment_service.reschedule_appointment(
                phone=context.contact_phone,
                nova_data=nova_data,
                novo_horario=novo_horario,
                nome=nome,
                api_key=context.api_key
            )

            # Marca como processado para evitar loops
            await state_manager.set_state_data("reagendamento_processado", True)

            if result_dict.get("success"):
                logger.info(f"[StateTrigger] Reagendamento automático bem-sucedido")

                # Log de segurança para auditoria
                SecurityGuards.log_security_event(
                    context.company_id, context.contact_phone,
                    "SUCCESSFUL_RESCHEDULING", f"Auto-rescheduled to {nova_data} {novo_horario}"
                )

                # Limpa dados temporários de reagendamento
                await state_manager.set_state_data("reagendamento_data", None)
                await state_manager.set_state_data("reagendamento_horario", None)

                return f"\n\n{result_dict['message']}"
            else:
                logger.error(f"[StateTrigger] Reagendamento falhou: {result_dict.get('message')}")
                return f"\n\n{result_dict.get('message', '❌ Erro no reagendamento.')}"

        except Exception as e:
            logger.error(f"[StateTrigger] Erro no reagendamento automático: {e}")
            SecurityGuards.log_security_event(
                context.company_id, context.contact_phone,
                "RESCHEDULING_ERROR", str(e)
            )
            return "\n\n❌ Ocorreu um erro ao processar seu reagendamento. Por favor, tente novamente."

    @staticmethod
    async def _check_step_transitions(
        wrapper,
        user_message: str,
        openai_api_key: str,
    ) -> None:
        """
        Verifica se deve fazer transições de step baseadas na mensagem do usuário.
        """
        context = wrapper.context
        state_manager = await context.get_state_manager()
        current_step = state_manager.state.current_step

        # Análise semântica simples para extrair informações
        await StateTriggerHandler._extract_and_save_data(
            wrapper,
            user_message,
            current_step,
            openai_api_key,
        )

    @staticmethod
    async def _extract_and_save_data(
        wrapper,
        user_message: str,
        current_step: int,
        openai_api_key: str,
    ) -> None:
        """
        Extrai e salva dados relevantes da mensagem do usuário baseado no step atual.
        """
        context = wrapper.context
        state_manager = await context.get_state_manager()

        # Step 0 ou 1: Identifica tratamento (funciona em qualquer step inicial)
        if current_step <= 1 and not state_manager.is_field_filled("tratamento"):
            tratamento = await StateTriggerHandler._extract_treatment_intent(
                user_message,
                openai_api_key,
            )
            logger.info(f"[StateTrigger] Tratamento extraído de '{user_message}': {tratamento}")
            if tratamento:
                # Salva o tratamento primeiro
                await state_manager.set_state_data("tratamento", tratamento)
                logger.info(f"[StateTrigger] Tratamento salvo: {tratamento}")

                # Agora valida transição para step 2
                can_transition, error = await StateValidationGuards.validate_state_transition(wrapper, 2)
                logger.info(f"[StateTrigger] Pode transicionar para step 2: {can_transition} ({error})")
                if can_transition:
                    await state_manager.transition_to_step(2)
                    logger.info(f"[StateTrigger] Transição para step 2 realizada")
                else:
                    logger.warning(f"[StateTrigger] Transição negada para step 2: {error}")
            else:
                logger.info(f"[StateTrigger] Nenhum tratamento identificado em '{user_message}'")
        # Step 2: Identifica se é cliente novo ou retorno
        elif current_step == 2 and not state_manager.is_field_filled("cliente"):
            cliente_type = await StateTriggerHandler._extract_customer_type(
                user_message,
                openai_api_key,
            )
            if cliente_type:
                # Salva o tipo de cliente primeiro
                await state_manager.set_state_data("cliente", cliente_type)
                logger.info(f"[StateTrigger] Tipo de cliente salvo: {cliente_type}")

                # Agora valida transição para step 3
                can_transition, error = await StateValidationGuards.validate_state_transition(wrapper, 3)
                if can_transition:
                    await state_manager.transition_to_step(3)
                    logger.info(f"[StateTrigger] Transição para step 3 realizada")
                else:
                    logger.warning(f"[StateTrigger] Transição negada para step 3: {error}")

        # QUALQUER STEP: Captura escolha de horário
        # Para step 9 (reagendamento), captura para campos específicos de reagendamento
        if current_step == 9 and not state_manager.is_field_filled("reagendamento_data"):
            # Usa apenas os slots que foram oferecidos pelo LLM, não todos os disponíveis
            offered_slots = state_manager.get_offered_slots()
            slots_to_use = offered_slots if offered_slots else context.available_slots

            logger.info(f"[StateTrigger] Step 9 - Analisando escolha de novo horário usando {len(slots_to_use)} slots")

            schedule_data = await StateTriggerHandler._extract_schedule_choice(
                user_message,
                slots_to_use,
                openai_api_key,
            )
            if schedule_data:
                # Sanitiza dados de horário
                sanitized_schedule = await StateValidationGuards.sanitize_input_data(schedule_data)

                # Salva os dados de reagendamento
                await state_manager.set_state_data("reagendamento_data", sanitized_schedule["data"])
                await state_manager.set_state_data("reagendamento_horario", sanitized_schedule["horario"])
                logger.info(f"[StateTrigger] Novo horário para reagendamento salvo: {sanitized_schedule}")

        # Para outros steps, captura para campos normais
        elif not state_manager.is_field_filled("data"):
            # Usa apenas os slots que foram oferecidos pelo LLM, não todos os disponíveis
            offered_slots = state_manager.get_offered_slots()
            slots_to_use = offered_slots if offered_slots else context.available_slots

            logger.info(f"[StateTrigger] Analisando escolha de horário usando {len(slots_to_use)} slots {'oferecidos' if offered_slots else 'disponíveis'}")

            schedule_data = await StateTriggerHandler._extract_schedule_choice(
                user_message,
                slots_to_use,
                openai_api_key,
            )
            if schedule_data:
                # Sanitiza dados de horário
                sanitized_schedule = await StateValidationGuards.sanitize_input_data(schedule_data)

                # Salva os dados de agendamento primeiro
                await state_manager.set_state_data("data", sanitized_schedule["data"])
                await state_manager.set_state_data("horario", sanitized_schedule["horario"])
                logger.info(f"[StateTrigger] Horário salvo: {sanitized_schedule}")

                # Agora valida transição para step 5
                can_transition, error = await StateValidationGuards.validate_state_transition(wrapper, 5)
                if can_transition:
                    await state_manager.transition_to_step(5)
                    logger.info(f"[StateTrigger] Transição para step 5 realizada")
                else:
                    logger.warning(f"[StateTrigger] Transição negada para step 5: {error}")

        # QUALQUER STEP: Verifica intenção de cancelamento
        if await StateTriggerHandler._extract_cancellation_intent(
            user_message,
            openai_api_key,
        ):
            logger.info(f"[StateTrigger] Intenção de cancelamento detectada")
            # Transiciona para step 8 (cancelamento)
            await state_manager.transition_to_step(8)
            logger.info(f"[StateTrigger] Transição para step 8 (cancelamento) realizada")

        # QUALQUER STEP: Verifica intenção de reagendamento
        if await StateTriggerHandler._extract_reschedule_intent(
            user_message,
            openai_api_key,
        ):
            logger.info(f"[StateTrigger] Intenção de reagendamento detectada")
            # Transiciona para step 9 (reagendamento)
            await state_manager.transition_to_step(9)
            logger.info(f"[StateTrigger] Transição para step 9 (reagendamento) realizada")

        # QUALQUER STEP: Captura nome completo (pode acontecer a qualquer momento)
        if not state_manager.is_field_filled("nome"):
            nome = await StateTriggerHandler._extract_full_name(
                user_message,
                openai_api_key,
            )
            if nome:
                # Sanitiza nome
                sanitized_data = await StateValidationGuards.sanitize_input_data({"nome": nome})
                sanitized_nome = sanitized_data.get("nome")

                if sanitized_nome and len(sanitized_nome) >= 2:
                    await state_manager.set_state_data("nome", sanitized_nome)
                    logger.info(f"[StateTrigger] Nome capturado: {sanitized_nome}")

                    # Se já temos data e horário, avança para step 5
                    if state_manager.is_field_filled("data") and state_manager.is_field_filled("horario"):
                        can_transition, error = await StateValidationGuards.validate_state_transition(wrapper, 5)
                        if can_transition:
                            await state_manager.transition_to_step(5)
                            logger.info(f"[StateTrigger] Transição para step 5 realizada após capturar nome")
                        else:
                            logger.warning(f"[StateTrigger] Transição negada para step 5: {error}")
                else:
                    logger.warning(f"[StateTrigger] Nome inválido após sanitização: {nome} -> {sanitized_nome}")

    @staticmethod
    async def _extract_treatment_intent(
        message: str,
        openai_api_key: str,
    ) -> Optional[str]:
        """
        Extrai intenção de tratamento usando análise semântica com LLM.
        Substitui regex/keywords por verdadeira compreensão semântica.
        """
        try:
            client = StateTriggerHandler._openai_client(openai_api_key)

            logger.info(f"[StateTrigger] Análise semântica de tratamento: '{message}'")

            prompt = f"""
Analise a mensagem do cliente e identifique qual tratamento de serviços ele está buscando.

MENSAGEM DO CLIENTE: "{message}"

TRATAMENTOS DISPONÍVEIS:
- implante: quando perdeu dente, quer repor dente, prótese, implante dentário
- dor: quando tem dor de dente, algo doendo, incômodo, emergência
- limpeza: quando quer higienização, profilaxia, remover tártaro, limpeza
- clareamento: quando quer dentes mais brancos, clarear, branqueamento
- ortodontia: quando quer alinhar dentes, aparelho ortodôntico, corrigir posição
- restauração: quando tem cárie, buraco no dente, obturação, restaurar
- avaliação: quando quer consulta geral, check-up, não sabe o que precisa

RESPONDA APENAS UMA PALAVRA com o tratamento identificado ou "null" se não conseguir identificar.

Exemplos:
- "quero fazer um implante" → implante
- "estou com dor de dente" → dor
- "quero clarear os dentes" → clareamento
- "preciso de uma consulta" → avaliação
- "oi" → null

Tratamento identificado:"""

            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "user", "content": prompt}
                ],
                max_tokens=20,
                temperature=0.1
            )

            result = response.choices[0].message.content.strip().lower()

            # Valida se a resposta é um tratamento válido
            valid_treatments = ["implante", "dor", "limpeza", "clareamento", "ortodontia", "restauração", "avaliação"]

            if result in valid_treatments:
                logger.info(f"[StateTrigger] LLM identificou tratamento: '{result}' para mensagem '{message}'")
                return result
            elif result == "null":
                logger.info(f"[StateTrigger] LLM não identificou tratamento em: '{message}'")
                return None
            else:
                logger.warning(f"[StateTrigger] LLM retornou resposta inválida: '{result}', assumindo 'avaliação'")
                return "avaliação"

        except Exception as exc:
            logger.warning(
                "[StateTrigger] Análise semântica de tratamento falhou (%s)",
                type(exc).__name__,
            )
            # Fallback simples em caso de erro
            if any(word in message.lower() for word in ["implante", "prótese"]):
                return "implante"
            elif any(word in message.lower() for word in ["dor", "dói", "doendo"]):
                return "dor"
            elif any(word in message.lower() for word in ["limpeza", "higiene"]):
                return "limpeza"
            elif any(word in message.lower() for word in ["clareamento", "clarear", "branco"]):
                return "clareamento"
            elif any(word in message.lower() for word in ["aparelho", "ortodontia"]):
                return "ortodontia"
            elif any(word in message.lower() for word in ["cárie", "obturação", "restauração"]):
                return "restauração"
            else:
                return "avaliação"

    @staticmethod
    async def _extract_customer_type(
        message: str,
        openai_api_key: str,
    ) -> Optional[str]:
        """Extrai tipo de cliente usando análise semântica."""
        try:
            client = StateTriggerHandler._openai_client(openai_api_key)

            logger.info(f"[StateTrigger] Análise semântica de tipo de cliente: '{message}'")

            prompt = f"""
Analise a resposta do cliente e identifique se ele é novo ou retorno na empresa.

PERGUNTA FEITA: "é a sua primeira vez aqui na empresa ou você já é nosso cliente?"
RESPOSTA DO CLIENTE: "{message}"

RESPONDA APENAS UMA PALAVRA:
- "novo" se é primeira vez na empresa
- "retorno" se já foi cliente antes
- "null" se não conseguir identificar

Exemplos:
- "primeira vez" → novo
- "já vim antes" → retorno
- "sou cliente antigo" → retorno
- "nunca estive aí" → novo
- "não sei" → null

Tipo de cliente:"""

            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "user", "content": prompt}
                ],
                max_tokens=10,
                temperature=0.1
            )

            result = response.choices[0].message.content.strip().lower()

            if result in ["novo", "retorno"]:
                logger.info(f"[StateTrigger] LLM identificou tipo de cliente: '{result}' para mensagem '{message}'")
                return result
            elif result == "null":
                logger.info(f"[StateTrigger] LLM não identificou tipo de cliente em: '{message}'")
                return None
            else:
                logger.warning(f"[StateTrigger] LLM retornou resposta inválida: '{result}', assumindo 'novo'")
                return "novo"

        except Exception as exc:
            logger.warning(
                "[StateTrigger] Análise semântica de cliente falhou (%s)",
                type(exc).__name__,
            )
            # Fallback simples
            if any(word in message.lower() for word in ["primeira", "nunca", "novo", "não"]):
                return "novo"
            elif any(word in message.lower() for word in ["já", "retorno", "sim", "antes", "cliente"]):
                return "retorno"
            return None

    @staticmethod
    async def _extract_schedule_choice(
        message: str,
        available_slots: Optional[list],
        openai_api_key: str,
    ) -> Optional[dict]:
        """Extrai escolha de horário usando análise semântica."""
        if not available_slots:
            return None

        try:
            client = StateTriggerHandler._openai_client(openai_api_key)

            logger.info(f"[StateTrigger] Análise semântica de escolha de horário: '{message}'")

            # Prepara slots para o prompt (primeiros 10)
            slots_text = "\n".join([f"- {slot}" for slot in available_slots[:10]])

            prompt = f"""
Analise a mensagem do cliente e identifique qual horário ele escolheu da lista disponível.

HORÁRIOS DISPONÍVEIS:
{slots_text}

MENSAGEM DO CLIENTE: "{message}"

INSTRUÇÕES INTELIGENTES:
- Se o cliente mencionar apenas um horário (ex: "08:30", "às 14h"), encontre o slot correspondente na lista
- Se mencionar dia da semana (ex: "sexta"), combine com horário mencionado
- Se mencionar "manhã" ou "tarde", escolha o primeiro slot correspondente
- Se mencionar um dos slots exatos da lista, use esse
- Seja flexível com formatos: "8h30", "08:30", "8:30", "oito e meia"

REGRAS DE MATCHING:
1. Priorize correspondência EXATA de horário nos slots disponíveis
2. Se houver múltiplos slots no mesmo horário, escolha o mais próximo (menor data)
3. Se não conseguir fazer match específico, retorne null

Se encontrar um match, responda APENAS no formato:
DD/MM/YYYY HH:MM

Se não conseguir identificar, responda:
null

Exemplos INTELIGENTES:
- "08:30" + slots ["04/07/2025 08:30", "05/07/2025 08:30"] → 04/07/2025 08:30
- "às 14h" + slot "04/07/2025 14:00" → 04/07/2025 14:00
- "sexta de manhã" + slot "04/07/2025 09:00" (se 04/07 for sexta) → 04/07/2025 09:00
- "tanto faz" → null

Horário escolhido:"""

            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "user", "content": prompt}
                ],
                max_tokens=30,
                temperature=0.1
            )

            result = response.choices[0].message.content.strip()

            if result == "null":
                logger.info(f"[StateTrigger] LLM não identificou escolha de horário em: '{message}'")
                return None

            # Valida se o resultado está no formato correto e é um slot disponível
            # Extrai strings dos slots (suporte para dict ou string)
            available_slot_strings = []
            for slot in available_slots:
                if isinstance(slot, dict):
                    available_slot_strings.append(slot["slot"])
                else:
                    available_slot_strings.append(slot)

            if result in available_slot_strings:
                parts = result.split(' ')
                if len(parts) >= 2:
                    logger.info(f"[StateTrigger] LLM identificou escolha de horário: '{result}'")
                    return {
                        "data": parts[0],
                        "horario": parts[1]
                    }

            logger.warning(f"[StateTrigger] LLM retornou horário inválido: '{result}'")
            return None

        except Exception as exc:
            logger.warning(
                "[StateTrigger] Análise semântica de horário falhou (%s)",
                type(exc).__name__,
            )

            # Fallback INTELIGENTE: busca pattern de horário na mensagem
            import re

            # Procura padrões de horário: 08:30, 8h30, 8:30, etc.
            time_patterns = [
                r'\b(\d{1,2}):(\d{2})\b',           # 08:30, 8:30
                r'\b(\d{1,2})h(\d{2})\b',          # 8h30
                r'\b(\d{1,2})h\b',                 # 8h (assume :00)
                r'\bàs (\d{1,2})\b'                # às 8
            ]

            for pattern in time_patterns:
                match = re.search(pattern, message.lower())
                if match:
                    if pattern.endswith(r'h\b'):  # Formato 8h
                        hour = int(match.group(1))
                        minute = 0
                    elif pattern.endswith(r'\b'):  # Formato "às 8"
                        hour = int(match.group(1))
                        minute = 0
                    else:  # Formatos com minutos
                        hour = int(match.group(1))
                        minute = int(match.group(2)) if match.group(2) else 0

                    # Formata horário padronizado
                    time_str = f"{hour:02d}:{minute:02d}"

                    # Procura esse horário nos slots disponíveis
                    for slot in available_slots[:15]:
                        if time_str in slot:
                            parts = slot.split(' ')
                            if len(parts) >= 2:
                                logger.info(f"[StateTrigger] Fallback encontrou match: {time_str} → {slot}")
                                return {"data": parts[0], "horario": parts[1]}

            return None

    @staticmethod
    async def _extract_cancellation_intent(
        message: str,
        openai_api_key: str,
    ) -> bool:
        """
        Extrai intenção de cancelamento usando análise semântica com LLM.
        """
        try:
            client = StateTriggerHandler._openai_client(openai_api_key)

            logger.info(f"[StateTrigger] Análise semântica de cancelamento: '{message}'")

            prompt = f"""
Analise a mensagem do cliente e identifique se ele quer CANCELAR um agendamento.

MENSAGEM DO CLIENTE: "{message}"

EXEMPLOS DE CANCELAMENTO:
- "quero cancelar"
- "preciso desmarcar"
- "não vou poder ir"
- "cancela pra mim"
- "desmarca por favor"
- "surgiu um imprevisto"
- "não vai dar certo"
- "preciso remarcar" (às vezes indica cancelamento primeiro)

EXEMPLOS QUE NÃO SÃO CANCELAMENTO:
- "quero agendar"
- "qual horário disponível"
- "obrigado"
- perguntas sobre tratamento

RESPONDA APENAS: true ou false

É cancelamento:"""

            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "user", "content": prompt}
                ],
                max_tokens=10,
                temperature=0.1
            )

            result = response.choices[0].message.content.strip().lower()

            is_cancellation = result == "true"
            logger.info(f"[StateTrigger] LLM detectou intenção de cancelamento: {is_cancellation}")
            return is_cancellation

        except Exception as exc:
            logger.warning(
                "[StateTrigger] Análise semântica de cancelamento falhou (%s)",
                type(exc).__name__,
            )
            # Fallback simples
            cancel_keywords = ["cancelar", "desmarcar", "cancela", "desmarca", "não vou poder", "imprevisto"]
            return any(keyword in message.lower() for keyword in cancel_keywords)

    @staticmethod
    async def _extract_reschedule_intent(
        message: str,
        openai_api_key: str,
    ) -> bool:
        """
        Extrai intenção de reagendamento usando análise semântica com LLM.
        """
        try:
            client = StateTriggerHandler._openai_client(openai_api_key)

            logger.info(f"[StateTrigger] Análise semântica de reagendamento: '{message}'")

            prompt = f"""
Analise a mensagem do cliente e identifique se ele quer REAGENDAR/REMARCAR um agendamento.

MENSAGEM DO CLIENTE: "{message}"

EXEMPLOS DE REAGENDAMENTO:
- "quero remarcar"
- "preciso reagendar"
- "pode mudar o horário"
- "mudou meu horário, preciso trocar"
- "não vai dar nesse dia, pode ser outro?"
- "preciso trocar o dia"
- "tem outro horário disponível?"
- "esse horário não dá mais"

EXEMPLOS QUE NÃO SÃO REAGENDAMENTO:
- "quero cancelar" (só cancelar, sem remarcar)
- "quero agendar" (primeiro agendamento)
- "obrigado"
- perguntas sobre o agendamento atual

RESPONDA APENAS: true ou false

É reagendamento:"""

            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "user", "content": prompt}
                ],
                max_tokens=10,
                temperature=0.1
            )

            result = response.choices[0].message.content.strip().lower()

            is_reschedule = result == "true"
            logger.info(f"[StateTrigger] LLM detectou intenção de reagendamento: {is_reschedule}")
            return is_reschedule

        except Exception as exc:
            logger.warning(
                "[StateTrigger] Análise semântica de reagendamento falhou (%s)",
                type(exc).__name__,
            )
            # Fallback simples
            reschedule_keywords = ["remarcar", "reagendar", "trocar o dia", "mudar o horário", "outro horário", "trocar horário"]
            return any(keyword in message.lower() for keyword in reschedule_keywords)

    @staticmethod
    async def _extract_full_name(
        message: str,
        openai_api_key: str,
    ) -> Optional[str]:
        """Extrai nome completo usando análise semântica."""
        try:
            client = StateTriggerHandler._openai_client(openai_api_key)

            logger.info(f"[StateTrigger] Análise semântica de nome: '{message}'")

            prompt = f"""
Extraia o nome completo da pessoa a partir da mensagem.

MENSAGEM: "{message}"

REGRAS:
- Extraia apenas o nome da pessoa (nome e sobrenome se possível)
- Ignore saudações, artigos, preposições
- Ignore palavras como: "oi", "olá", "meu nome é", "me chamo", "sou", etc.
- O nome deve ter pelo menos 2 caracteres
- Prefira nome completo (nome + sobrenome)

Se encontrar um nome válido, responda APENAS o nome extraído.
Se não encontrar nome válido, responda: null

Exemplos:
- "Meu nome é João Silva" → João Silva
- "Me chamo Maria" → Maria
- "Oi, sou Pedro Santos" → Pedro Santos
- "João" → João
- "sim, claro" → null
- "ok" → null

Nome extraído:"""

            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "user", "content": prompt}
                ],
                max_tokens=20,
                temperature=0.1
            )

            result = response.choices[0].message.content.strip()

            if result == "null":
                logger.info(f"[StateTrigger] LLM não identificou nome em: '{message}'")
                return None

            # Valida se é um nome válido (tem pelo menos 2 caracteres alfabéticos)
            if len(result) >= 2 and any(c.isalpha() for c in result):
                logger.info(f"[StateTrigger] LLM identificou nome: '{result}' para mensagem '{message}'")
                return result.strip()

            logger.warning(f"[StateTrigger] LLM retornou nome inválido: '{result}'")
            return None

        except Exception as exc:
            logger.warning(
                "[StateTrigger] Análise semântica de nome falhou (%s)",
                type(exc).__name__,
            )

            # Fallback simples: procura por palavras capitalizadas
            words = message.split()
            ignore_words = {"oi", "olá", "meu", "nome", "é", "sou", "me", "chamo", "obrigado", "obrigada", "sim", "claro", "ok"}

            name_words = []
            for word in words:
                clean_word = ''.join(c for c in word if c.isalpha())
                if (clean_word.lower() not in ignore_words and
                    len(clean_word) > 1 and
                    clean_word.istitle()):
                    name_words.append(clean_word)

            if len(name_words) >= 2:
                return " ".join(name_words)
            elif len(name_words) == 1 and len(name_words[0]) > 2:
                return name_words[0]

            return None

    @staticmethod
    async def _extract_scheduling_preference(
        message: str,
        openai_api_key: str,
    ) -> Optional[str]:
        """
        Extrai preferências de agendamento usando análise semântica.
        """
        try:
            client = StateTriggerHandler._openai_client(openai_api_key)

            logger.info(f"[StateTrigger] Análise semântica de preferência: '{message}'")

            prompt = f"""
Analise a mensagem do cliente e identifique preferências de agendamento.

MENSAGEM DO CLIENTE: "{message}"

IDENTIFIQUE E RETORNE:
- Dia da semana específico (segunda, terça, quarta, quinta, sexta, sábado, domingo)
- Período do dia (manhã, tarde, noite)
- Data específica
- Outras preferências temporais

Se identificar preferência clara, responda APENAS a preferência.
Se não identificar preferência, responda: null

Exemplos:
- "tem horário sábado?" → sábado
- "prefiro pela manhã" → manhã
- "pode ser à tarde" → tarde
- "semana que vem" → próxima semana
- "ok" → null

Preferência identificada:"""

            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "user", "content": prompt}
                ],
                max_tokens=20,
                temperature=0.1
            )

            result = response.choices[0].message.content.strip().lower()

            if result == "null":
                logger.info(f"[StateTrigger] LLM não identificou preferência em: '{message}'")
                return None

            logger.info(f"[StateTrigger] LLM identificou preferência: '{result}' para mensagem '{message}'")
            return result

        except Exception as exc:
            logger.warning(
                "[StateTrigger] Análise semântica de preferência falhou (%s)",
                type(exc).__name__,
            )
            # Fallback simples
            message_lower = message.lower()
            if any(day in message_lower for day in ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]):
                for day in ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]:
                    if day in message_lower:
                        return day
            elif any(period in message_lower for period in ["manhã", "tarde", "noite"]):
                for period in ["manhã", "tarde", "noite"]:
                    if period in message_lower:
                        return period
            return None


class StateValidationTrigger:
    """
    Triggers para validação e correção de estado.
    """

    @staticmethod
    async def validate_scheduling_data(wrapper) -> bool:
        """
        Valida se os dados de agendamento estão consistentes.

        Returns:
            bool: True se os dados são válidos
        """
        context = wrapper.context
        state_manager = await context.get_state_manager()

        required_fields = ["nome", "data", "horario"]
        for field in required_fields:
            if not state_manager.is_field_filled(field):
                logger.warning(f"[StateValidation] Campo obrigatório faltando: {field}")
                return False

        # Valida formato de data e horário
        data = state_manager.get_state_data("data")
        horario = state_manager.get_state_data("horario")

        if not StateTriggerHandler._validate_date_format(data):
            logger.warning(f"[StateValidation] Formato de data inválido: {data}")
            return False

        if not StateTriggerHandler._validate_time_format(horario):
            logger.warning(f"[StateValidation] Formato de horário inválido: {horario}")
            return False

        # Verifica se o slot ainda está disponível
        data_hora = f"{data} {horario}"
        if context.available_slots and data_hora not in context.available_slots:
            logger.warning(f"[StateValidation] Slot não disponível: {data_hora}")
            return False

        return True

    @staticmethod
    def _validate_date_format(date_str: str) -> bool:
        """Valida formato DD/MM/YYYY."""
        import re
        pattern = r'^\d{2}/\d{2}/\d{4}$'
        return bool(re.match(pattern, date_str))

    @staticmethod
    def _validate_time_format(time_str: str) -> bool:
        """Valida formato HH:MM."""
        import re
        pattern = r'^\d{2}:\d{2}$'
        return bool(re.match(pattern, time_str))
