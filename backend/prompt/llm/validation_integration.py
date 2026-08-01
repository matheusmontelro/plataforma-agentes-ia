
"""
Integração do serviço de validação com o fluxo de conversa do assistente.

Este módulo contém funções que integram o serviço de validação contextual
com o fluxo de processamento de mensagens e confirmação de agendamentos.
"""

import logging
from typing import Optional, Dict, Any

from .validation_service import (
   get_full_conversation_history,
   validate_all_extracted_data,
   analyze_appointment_confirmation,
   handle_data_validation
)

logger = logging.getLogger(__name__)

def validate_conversation_state(state_machine) -> Optional[str]:
   """
   Valida o estado atual da conversa antes de avançar no fluxo.

   Esta função deve ser chamada em pontos críticos do fluxo de conversa,
   particularmente antes de confirmar agendamentos ou avançar steps críticos.

   Args:
       state_machine: Instância de ConversationStateMachine

   Returns:
       Mensagem para o usuário se necessário, ou None para continuar fluxo normal
   """
   # Se o step atual não é crítico, skip
   current_step = state_machine.get_current_step()
   if current_step < 4:  # Steps 0-3 são informacionais
       return None

   # Obter histórico da conversa
   conversation_history = get_full_conversation_history(
       state_machine.db_session,
       state_machine.phone,
       state_machine.company_id
   )

   if not conversation_history:
       logger.warning("[ValidationIntegration] Não foi possível obter histórico da conversa")
       return None

   # Validar todos os dados extraídos
   validation_result = validate_all_extracted_data(state_machine, conversation_history)

   # Processar resultados da validação
   correction_message = handle_data_validation(state_machine, validation_result)
   if correction_message:
       # Resetar flags quando campos faltantes forem identificados
       data = state_machine.get_state_data("data")
       horario = state_machine.get_state_data("horario")

       # Resetar todos os flags de confirmação para forçar novo ciclo de validação
       state_machine.set_state_data("agendamento_confirmado", False)
       state_machine.set_state_data("slot_verified", False)
       state_machine.set_state_data("confirmation_asked", False)
       state_machine.set_state_data("user_confirmed", False)

       # Voltar para o step adequado
       state_machine.set_current_step(4)  # Step de coleta de data/horário

       logger.info(f"[ValidationIntegration] Correção necessária: {correction_message}")

       # Se temos data e horário, incluí-los na mensagem para o usuário confirmar especificamente
       if data and horario:
         friendly_date = format_friendly_date(data)
         correction_message = f"Temos disponibilidade {friendly_date}. Qual horário seria melhor para você?"

       return correction_message

   # Nenhuma correção necessária, continuar fluxo normal
   return None

def validate_before_appointment_confirmation(state_machine) -> bool:
   """
   Valida o contexto completo antes de confirmar um agendamento.

   Esta função deve ser chamada no momento em que o sistema está prestes
   a confirmar um agendamento, para garantir que todos os dados estão corretos.

   Args:
       state_machine: Instância de ConversationStateMachine

   Returns:
       Boolean indicando se o agendamento pode ser confirmado
   """
   # Obter histórico da conversa
   conversation_history = get_full_conversation_history(
       state_machine.db_session,
       state_machine.phone,
       state_machine.company_id
   )

   if not conversation_history:
       logger.error("[ValidationIntegration] Não foi possível obter histórico para validação pré-confirmação")
       return False

   # Logar o início da validação com nível ERROR para garantir visibilidade
   logger.error(f"[ValidationIntegration] Iniciando validação de confirmação para phone={state_machine.phone}")
   logger.error(f"[ValidationIntegration] Dados atuais: data={state_machine.get_state_data('data')}, hora={state_machine.get_state_data('horario')}")

   # Analisar se o agendamento pode ser confirmado
   valid, details = analyze_appointment_confirmation(state_machine, conversation_history)

   # Logar resultado detalhado com nível ERROR para garantir visibilidade
   if valid:
       if details.get("updated_fields"):
           logger.error(f"[ValidationIntegration] Confirmação válida com correções: {details['updated_fields']}")
       else:
           logger.error("[ValidationIntegration] Confirmação válida sem correções necessárias")
   else:
       logger.error(f"[ValidationIntegration] Confirmação BLOQUEADA: {details}")

       # Resetar flags quando a validação falhar
       state_machine.set_state_data("agendamento_confirmado", False)
       state_machine.set_state_data("slot_verified", False)
       state_machine.set_state_data("confirmation_asked", False)
       state_machine.set_state_data("user_confirmed", False)

   return valid

# Função principal para integrar com o confirm_appointment do agendamento_logic.py
def enhanced_appointment_confirmation(state_machine) -> tuple:
   """
   Versão aprimorada da confirmação de agendamento com validação contextual.

   Args:
       state_machine: Instância de ConversationStateMachine

   Returns:
       Tupla (proceed, reason) indicando se deve prosseguir com agendamento e por quê
   """
   # Verifica se podemos confirmar o agendamento
   if not state_machine.can_confirm_appointment():
       return False, "state_machine_validation_failed"

   # Verifica se já está em período de cooldown
   if state_machine.has_recent_confirmation():
       cooldown_remaining = state_machine.get_confirmation_cooldown_remaining()
       logger.warning(
           f"[ValidationIntegration] Tentativa de confirmação durante cooldown. "
           f"Tempo restante: {cooldown_remaining}s"
       )
       return False, "in_cooldown_period"

   # Validação contextual semântica
   validation_passed = validate_before_appointment_confirmation(state_machine)
   if not validation_passed:
       logger.error("[ValidationIntegration] Agendamento impedido por validação contextual falha")
       return False, "contextual_validation_failed"

   # Se todas as verificações passaram, pode confirmar
   return True, "validation_passed"

def format_friendly_date(date_str):
    """
    Converte uma data no formato DD/MM/YYYY para um formato mais amigável
    como 'hoje', 'amanhã', ou 'Dia da semana, DD/MM/YYYY'
    """
    from datetime import datetime, timedelta

    # Dicionário para mapear os dias da semana em inglês para português
    dias_semana = {
        "Monday": "Segunda-feira",
        "Tuesday": "Terça-feira",
        "Wednesday": "Quarta-feira",
        "Thursday": "Quinta-feira",
        "Friday": "Sexta-feira",
        "Saturday": "Sábado",
        "Sunday": "Domingo"
    }

    # Converter string para objeto datetime
    date_obj = datetime.strptime(date_str, "%d/%m/%Y")
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    tomorrow = today + timedelta(days=1)

    # Formatar data conforme necessário
    if date_obj.date() == today.date():
        return f"hoje, {date_str}"
    elif date_obj.date() == tomorrow.date():
        return f"amanhã, {date_str}"
    else:
        # Obter nome do dia da semana em inglês
        weekday_en = date_obj.strftime("%A")
        # Traduzir para português
        weekday_pt = dias_semana.get(weekday_en, weekday_en)
        return f"{weekday_pt}, {date_str}"
