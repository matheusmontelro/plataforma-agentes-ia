"""
Message Analytics - Análise de Mensagens por Empresa

Este módulo analisa mensagens enviadas pela IA (from_me=True) para:
- Contabilizar mensagens por dia/mês por empresa
- Calcular caracteres enviados
- Estimar tokens utilizados
- Projetar custos mensais

Estrutura da tabela messages:
- id: BigInteger (PK)
- client_id: Integer
- company_id: BigInteger
- contact_phone: String(20)
- message_type: String(10) - text, image, audio, video
- content: Text - conteúdo da mensagem
- sender_phone: String(20)
- sender_name: String(255)
- from_me: Boolean - True = IA enviou, False = usuário enviou
- timestamp: TIMESTAMP(timezone=True)
- photo: Text
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import func, and_, extract, case
from collections import defaultdict
import tiktoken

logger = logging.getLogger(__name__)

class MessageAnalytics:
    """Análise de mensagens enviadas pela IA por empresa"""

    def __init__(self, db: Session):
        self.db = db
        # Inicializa tokenizer do GPT-4 (cl100k_base)
        try:
            self.tokenizer = tiktoken.get_encoding("cl100k_base")
        except Exception as e:
            logger.warning(f"Erro ao carregar tokenizer: {e}. Usando aproximação.")
            self.tokenizer = None

    def count_tokens(self, text: str) -> int:
        """
        Conta tokens em um texto usando tiktoken.
        Se tokenizer não disponível, usa aproximação: ~4 chars = 1 token
        """
        if self.tokenizer:
            try:
                return len(self.tokenizer.encode(text))
            except Exception as e:
                logger.warning(f"Erro ao tokenizar: {e}")

        # Fallback: aproximação
        return len(text) // 4

    def get_messages_stats_by_company(
        self,
        company_id: Optional[int] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        only_ai_messages: bool = True
    ) -> Dict:
        """
        Retorna estatísticas de mensagens por empresa

        Args:
            company_id: ID da empresa (None = todas)
            start_date: Data inicial (None = últimos 30 dias)
            end_date: Data final (None = hoje)
            only_ai_messages: Se True, conta apenas mensagens da IA (from_me=True)

        Returns:
            Dict com estatísticas por empresa
        """
        from backend.models import Message

        # Define período padrão (últimos 30 dias)
        if not end_date:
            end_date = datetime.now()
        if not start_date:
            start_date = end_date - timedelta(days=30)

        # Constrói query base
        query = self.db.query(
            Message.company_id,
            func.count(Message.id).label('total_messages'),
            func.sum(func.length(Message.content)).label('total_chars')
        )

        # Filtros
        filters = [
            Message.timestamp >= start_date,
            Message.timestamp <= end_date
        ]

        if only_ai_messages:
            filters.append(Message.from_me == True)

        if company_id:
            filters.append(Message.company_id == company_id)

        query = query.filter(and_(*filters))
        query = query.group_by(Message.company_id)

        results = query.all()

        # Processa resultados
        stats = {}
        for row in results:
            company_id_result = row.company_id
            total_messages = row.total_messages
            total_chars = row.total_chars or 0

            # Estima tokens
            # Como temos total de chars, estimamos tokens
            estimated_tokens = total_chars // 4  # Aproximação básica

            # Calcula médias diárias
            days_in_period = (end_date - start_date).days or 1
            avg_messages_per_day = total_messages / days_in_period
            avg_chars_per_day = total_chars / days_in_period
            avg_tokens_per_day = estimated_tokens / days_in_period

            # Projeção mensal (30 dias)
            monthly_messages = avg_messages_per_day * 30
            monthly_chars = avg_chars_per_day * 30
            monthly_tokens = avg_tokens_per_day * 30

            # Estimativa de custo (GPT-4o-mini)
            # Input: ~$0.150 / 1M tokens, Output: ~$0.600 / 1M tokens
            # Consideramos 70% output (respostas da IA)
            input_tokens = monthly_tokens * 0.3
            output_tokens = monthly_tokens * 0.7

            estimated_cost_usd = (
                (input_tokens / 1_000_000) * 0.150 +
                (output_tokens / 1_000_000) * 0.600
            )
            estimated_cost_brl = estimated_cost_usd * 5.5  # Aproximação USD->BRL

            stats[company_id_result] = {
                'period': {
                    'start': start_date.isoformat(),
                    'end': end_date.isoformat(),
                    'days': days_in_period
                },
                'total': {
                    'messages': total_messages,
                    'characters': total_chars,
                    'estimated_tokens': estimated_tokens
                },
                'daily_average': {
                    'messages': round(avg_messages_per_day, 2),
                    'characters': round(avg_chars_per_day, 2),
                    'tokens': round(avg_tokens_per_day, 2)
                },
                'monthly_projection': {
                    'messages': round(monthly_messages, 0),
                    'characters': round(monthly_chars, 0),
                    'tokens': round(monthly_tokens, 0),
                    'estimated_cost_usd': round(estimated_cost_usd, 2),
                    'estimated_cost_brl': round(estimated_cost_brl, 2)
                }
            }

        return stats

    def get_detailed_token_analysis(
        self,
        company_id: int,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        sample_size: int = 1000
    ) -> Dict:
        """
        Análise detalhada de tokens usando tokenização real
        Analisa uma amostra de mensagens para maior precisão

        Args:
            company_id: ID da empresa
            start_date: Data inicial
            end_date: Data final
            sample_size: Número de mensagens para analisar

        Returns:
            Dict com análise detalhada de tokens
        """
        from backend.models import Message

        if not end_date:
            end_date = datetime.now()
        if not start_date:
            start_date = end_date - timedelta(days=30)

        # Busca amostra de mensagens
        query = self.db.query(Message).filter(
            and_(
                Message.company_id == company_id,
                Message.from_me == True,
                Message.timestamp >= start_date,
                Message.timestamp <= end_date
            )
        ).order_by(func.random()).limit(sample_size)

        messages = query.all()

        if not messages:
            return {
                'error': 'Nenhuma mensagem encontrada no período',
                'company_id': company_id,
                'period': f"{start_date.date()} a {end_date.date()}"
            }

        # Analisa tokens reais
        total_tokens = 0
        total_chars = 0
        message_count = len(messages)

        for msg in messages:
            content = msg.content or ""
            total_chars += len(content)
            total_tokens += self.count_tokens(content)

        # Calcula médias
        avg_tokens_per_message = total_tokens / message_count if message_count > 0 else 0
        avg_chars_per_message = total_chars / message_count if message_count > 0 else 0
        chars_per_token = total_chars / total_tokens if total_tokens > 0 else 4

        # Busca total de mensagens no período
        total_messages_count = self.db.query(func.count(Message.id)).filter(
            and_(
                Message.company_id == company_id,
                Message.from_me == True,
                Message.timestamp >= start_date,
                Message.timestamp <= end_date
            )
        ).scalar()

        # Projeção usando média real
        total_estimated_tokens = avg_tokens_per_message * total_messages_count

        # Projeção mensal
        days_in_period = (end_date - start_date).days or 1
        daily_avg_messages = total_messages_count / days_in_period
        monthly_messages = daily_avg_messages * 30
        monthly_tokens = avg_tokens_per_message * monthly_messages

        # Custos (GPT-4o-mini)
        input_tokens = monthly_tokens * 0.3
        output_tokens = monthly_tokens * 0.7

        estimated_cost_usd = (
            (input_tokens / 1_000_000) * 0.150 +
            (output_tokens / 1_000_000) * 0.600
        )
        estimated_cost_brl = estimated_cost_usd * 5.5

        return {
            'company_id': company_id,
            'period': {
                'start': start_date.isoformat(),
                'end': end_date.isoformat(),
                'days': days_in_period
            },
            'sample_analysis': {
                'sample_size': message_count,
                'total_messages_in_period': total_messages_count,
                'avg_tokens_per_message': round(avg_tokens_per_message, 2),
                'avg_chars_per_message': round(avg_chars_per_message, 2),
                'chars_per_token': round(chars_per_token, 2)
            },
            'period_totals': {
                'messages': total_messages_count,
                'estimated_tokens': round(total_estimated_tokens, 0),
                'daily_avg_messages': round(daily_avg_messages, 2),
                'daily_avg_tokens': round(total_estimated_tokens / days_in_period, 2)
            },
            'monthly_projection': {
                'messages': round(monthly_messages, 0),
                'tokens': round(monthly_tokens, 0),
                'estimated_cost_usd': round(estimated_cost_usd, 2),
                'estimated_cost_brl': round(estimated_cost_brl, 2)
            }
        }

    def get_messages_by_day(
        self,
        company_id: int,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> List[Dict]:
        """
        Retorna contagem de mensagens por dia

        Args:
            company_id: ID da empresa
            start_date: Data inicial (None = últimos 30 dias)
            end_date: Data final (None = hoje)

        Returns:
            Lista com estatísticas por dia
        """
        from backend.models import Message

        if not end_date:
            end_date = datetime.now()
        if not start_date:
            start_date = end_date - timedelta(days=30)

        query = self.db.query(
            func.date(Message.timestamp).label('date'),
            func.count(Message.id).label('message_count'),
            func.sum(func.length(Message.content)).label('total_chars')
        ).filter(
            and_(
                Message.company_id == company_id,
                Message.from_me == True,
                Message.timestamp >= start_date,
                Message.timestamp <= end_date
            )
        ).group_by(func.date(Message.timestamp)).order_by(func.date(Message.timestamp))

        results = query.all()

        daily_stats = []
        for row in results:
            date = row.date
            message_count = row.message_count
            total_chars = row.total_chars or 0
            estimated_tokens = total_chars // 4

            daily_stats.append({
                'date': date.isoformat(),
                'messages': message_count,
                'characters': total_chars,
                'estimated_tokens': estimated_tokens
            })

        return daily_stats

    def get_all_companies_summary(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> Dict:
        """
        Resumo consolidado de todas as empresas

        Returns:
            Dict com resumo geral e ranking de empresas
        """
        stats = self.get_messages_stats_by_company(
            company_id=None,
            start_date=start_date,
            end_date=end_date
        )

        if not stats:
            return {
                'total_companies': 0,
                'total_messages': 0,
                'total_estimated_cost_brl': 0
            }

        total_messages = sum(s['total']['messages'] for s in stats.values())
        total_monthly_tokens = sum(s['monthly_projection']['tokens'] for s in stats.values())
        total_monthly_cost_brl = sum(s['monthly_projection']['estimated_cost_brl'] for s in stats.values())

        # Ranking de empresas por volume
        ranking = sorted(
            [
                {
                    'company_id': company_id,
                    'monthly_messages': s['monthly_projection']['messages'],
                    'monthly_tokens': s['monthly_projection']['tokens'],
                    'monthly_cost_brl': s['monthly_projection']['estimated_cost_brl']
                }
                for company_id, s in stats.items()
            ],
            key=lambda x: x['monthly_messages'],
            reverse=True
        )

        return {
            'total_companies': len(stats),
            'period': stats[list(stats.keys())[0]]['period'] if stats else None,
            'totals': {
                'messages_in_period': total_messages,
                'monthly_projected_tokens': round(total_monthly_tokens, 0),
                'monthly_projected_cost_brl': round(total_monthly_cost_brl, 2)
            },
            'ranking': ranking[:10]  # Top 10 empresas
        }

    def export_analysis_report(
        self,
        company_id: Optional[int] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        output_file: Optional[str] = None
    ) -> str:
        """
        Gera relatório completo de análise em formato texto

        Args:
            company_id: ID da empresa (None = todas)
            start_date: Data inicial
            end_date: Data final
            output_file: Arquivo para salvar (None = retorna string)

        Returns:
            String com relatório formatado
        """
        if company_id:
            # Relatório individual
            stats = self.get_messages_stats_by_company(
                company_id=company_id,
                start_date=start_date,
                end_date=end_date
            )

            if not stats:
                return f"Nenhum dado encontrado para empresa {company_id}"

            company_data = stats[company_id]

            report = f"""
╔══════════════════════════════════════════════════════════════════╗
║        RELATÓRIO DE ANÁLISE DE MENSAGENS - EMPRESA {company_id:<6}        ║
╚══════════════════════════════════════════════════════════════════╝

📅 PERÍODO ANALISADO
   Início: {company_data['period']['start'][:10]}
   Fim:    {company_data['period']['end'][:10]}
   Dias:   {company_data['period']['days']}

📊 TOTAL NO PERÍODO
   Mensagens:         {company_data['total']['messages']:>10,}
   Caracteres:        {company_data['total']['characters']:>10,}
   Tokens estimados:  {company_data['total']['estimated_tokens']:>10,}

📈 MÉDIA DIÁRIA
   Mensagens/dia:     {company_data['daily_average']['messages']:>10.2f}
   Caracteres/dia:    {company_data['daily_average']['characters']:>10.2f}
   Tokens/dia:        {company_data['daily_average']['tokens']:>10.2f}

🗓️ PROJEÇÃO MENSAL (30 dias)
   Mensagens/mês:     {company_data['monthly_projection']['messages']:>10,.0f}
   Caracteres/mês:    {company_data['monthly_projection']['characters']:>10,.0f}
   Tokens/mês:        {company_data['monthly_projection']['tokens']:>10,.0f}

💰 CUSTO ESTIMADO MENSAL
   USD:  $ {company_data['monthly_projection']['estimated_cost_usd']:>8.2f}
   BRL:  R$ {company_data['monthly_projection']['estimated_cost_brl']:>8.2f}

ℹ️  NOTAS:
   - Considera apenas mensagens enviadas pela IA (from_me=True)
   - Custos baseados em GPT-4o-mini (Input: $0.15/1M, Output: $0.60/1M)
   - Assume 30% input e 70% output
   - Taxa de câmbio: R$ 5,50 / USD
"""
        else:
            # Relatório geral
            summary = self.get_all_companies_summary(start_date, end_date)

            report = f"""
╔══════════════════════════════════════════════════════════════════╗
║          RELATÓRIO CONSOLIDADO - TODAS AS EMPRESAS               ║
╚══════════════════════════════════════════════════════════════════╝

🏥 VISÃO GERAL
   Total de empresas:       {summary['total_companies']}
   Mensagens no período:    {summary['totals']['messages_in_period']:,}

🗓️ PROJEÇÃO MENSAL CONSOLIDADA
   Tokens/mês:              {summary['totals']['monthly_projected_tokens']:>10,.0f}
   Custo estimado:          R$ {summary['totals']['monthly_projected_cost_brl']:>8.2f}

🏆 TOP 10 EMPRESAS POR VOLUME

"""
            for i, company in enumerate(summary['ranking'], 1):
                report += f"   {i:>2}. Empresa {company['company_id']:<6} | {company['monthly_messages']:>8,.0f} msgs/mês | R$ {company['monthly_cost_brl']:>7.2f}/mês\n"

        if output_file:
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write(report)
            logger.info(f"Relatório salvo em: {output_file}")

        return report


# Função auxiliar para uso rápido
def analyze_company_messages(
    db: Session,
    company_id: Optional[int] = None,
    days: int = 30
) -> Dict:
    """
    Função auxiliar para análise rápida

    Args:
        db: Sessão do banco
        company_id: ID da empresa (None = todas)
        days: Número de dias para analisar

    Returns:
        Dict com estatísticas
    """
    analytics = MessageAnalytics(db)
    end_date = datetime.now()
    start_date = end_date - timedelta(days=days)

    if company_id:
        return analytics.get_messages_stats_by_company(
            company_id=company_id,
            start_date=start_date,
            end_date=end_date
        )
    else:
        return analytics.get_all_companies_summary(
            start_date=start_date,
            end_date=end_date
        )
