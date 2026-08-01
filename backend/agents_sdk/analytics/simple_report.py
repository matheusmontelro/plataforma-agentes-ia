#!/usr/bin/env python3
"""
Relatório Simples - Tabela de Custos e Mensagens por Empresa

Gera tabela com:
- Empresa ID
- Mensagens/dia
- Mensagens/mês
- Custo/dia (R$)
- Custo/mês (R$)
"""

import sys
from pathlib import Path
from datetime import datetime, timedelta

# Adiciona o diretório raiz do projeto ao path
project_root = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from backend.db import get_db
from backend.agents_sdk.analytics import MessageAnalytics


def generate_simple_table(days=30, use_real_tokenization=True):
    """Gera tabela simples com todas as empresas

    Args:
        days: Período em dias
        use_real_tokenization: Se True, usa análise detalhada com tokenização real (mais lento mas preciso)
    """

    db = next(get_db())
    analytics = MessageAnalytics(db)

    try:
        # Busca dados de todas as empresas
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)

        print("⏳ Analisando mensagens com tokenização real (pode demorar alguns segundos)...\n")

        if use_real_tokenization:
            # Primeiro, pega estatísticas básicas de todas as empresas
            basic_stats = analytics.get_messages_stats_by_company(
                company_id=None,
                start_date=start_date,
                end_date=end_date
            )

            # Para cada empresa, faz análise detalhada com tokenização real
            # mas usando amostra pequena (200 msgs) para ser mais rápido
            stats = {}
            total_companies = len(basic_stats)
            current = 0

            for company_id in basic_stats.keys():
                current += 1
                print(f"\r⏳ Processando empresa {company_id} ({current}/{total_companies})...", end='', flush=True)

                detailed = analytics.get_detailed_token_analysis(
                    company_id=company_id,
                    start_date=start_date,
                    end_date=end_date,
                    sample_size=200  # Amostra menor para ser mais rápido
                )

                if 'error' not in detailed:
                    # Converte formato da análise detalhada para o formato padrão
                    stats[company_id] = {
                        'period': detailed['period'],
                        'total': {
                            'messages': detailed['period_totals']['messages'],
                            'estimated_tokens': int(detailed['period_totals']['estimated_tokens'])
                        },
                        'daily_average': {
                            'messages': detailed['period_totals']['daily_avg_messages'],
                            'tokens': detailed['period_totals']['daily_avg_tokens']
                        },
                        'monthly_projection': {
                            'messages': detailed['monthly_projection']['messages'],
                            'tokens': detailed['monthly_projection']['tokens'],
                            'estimated_cost_brl': detailed['monthly_projection']['estimated_cost_brl'],
                            'estimated_cost_usd': detailed['monthly_projection']['estimated_cost_usd']
                        }
                    }

            print()  # Nova linha após o progresso
        else:
            stats = analytics.get_messages_stats_by_company(
                company_id=None,
                start_date=start_date,
                end_date=end_date
            )

        if not stats:
            print("❌ Nenhum dado encontrado")
            return

        # Ordena por ID da empresa
        sorted_companies = sorted(stats.items(), key=lambda x: x[0])

        # Cabeçalho
        print("\n" + "="*100)
        print("RELATÓRIO DE CUSTOS E MENSAGENS POR EMPRESA")
        print(f"Período: {days} dias ({start_date.strftime('%d/%m/%Y')} a {end_date.strftime('%d/%m/%Y')})")
        print("="*100)
        print()

        # Tabela
        print(f"{'Empresa':<10} {'Msgs/Dia':<12} {'Msgs/Mês':<12} {'Custo/Dia (R$)':<16} {'Custo/Mês (R$)':<16}")
        print("-"*100)

        total_daily_msgs = 0
        total_monthly_msgs = 0
        total_daily_cost = 0
        total_monthly_cost = 0

        for company_id, data in sorted_companies:
            daily_msgs = data['daily_average']['messages']
            monthly_msgs = data['monthly_projection']['messages']
            monthly_cost = data['monthly_projection']['estimated_cost_brl']
            daily_cost = monthly_cost / 30  # Custo diário

            print(f"{company_id:<10} {daily_msgs:>11.1f} {monthly_msgs:>11.0f} {daily_cost:>15.2f} {monthly_cost:>15.2f}")

            total_daily_msgs += daily_msgs
            total_monthly_msgs += monthly_msgs
            total_daily_cost += daily_cost
            total_monthly_cost += monthly_cost

        print("-"*100)
        print(f"{'TOTAL':<10} {total_daily_msgs:>11.1f} {total_monthly_msgs:>11.0f} {total_daily_cost:>15.2f} {total_monthly_cost:>15.2f}")
        print("="*100)

        # Resumo
        print(f"\n📊 RESUMO:")
        print(f"   • Total de empresas: {len(stats)}")
        print(f"   • Mensagens diárias (todas): {total_daily_msgs:,.1f}")
        print(f"   • Mensagens mensais (todas): {total_monthly_msgs:,.0f}")
        print(f"   • Custo diário (todas): R$ {total_daily_cost:,.2f}")
        print(f"   • Custo mensal (todas): R$ {total_monthly_cost:,.2f}")
        print()

    finally:
        db.close()


def generate_csv(days=30, output_file=None):
    """Gera CSV para exportação"""

    db = next(get_db())
    analytics = MessageAnalytics(db)

    try:
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)

        stats = analytics.get_messages_stats_by_company(
            company_id=None,
            start_date=start_date,
            end_date=end_date
        )

        if not stats:
            print("❌ Nenhum dado encontrado")
            return

        # Ordena por ID
        sorted_companies = sorted(stats.items(), key=lambda x: x[0])

        # Gera CSV
        lines = []
        lines.append("Companya_ID,Mensagens_Dia,Mensagens_Mes,Custo_Dia_BRL,Custo_Mes_BRL")

        for company_id, data in sorted_companies:
            daily_msgs = data['daily_average']['messages']
            monthly_msgs = data['monthly_projection']['messages']
            monthly_cost = data['monthly_projection']['estimated_cost_brl']
            daily_cost = monthly_cost / 30

            lines.append(f"{company_id},{daily_msgs:.2f},{monthly_msgs:.0f},{daily_cost:.2f},{monthly_cost:.2f}")

        csv_content = "\n".join(lines)

        if output_file:
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write(csv_content)
            print(f"✅ CSV salvo em: {output_file}")
        else:
            print("\n" + csv_content)

    finally:
        db.close()


def main():
    import argparse

    parser = argparse.ArgumentParser(description='Tabela simples de custos por empresa')
    parser.add_argument('--days', type=int, default=30, help='Período em dias (padrão: 30)')
    parser.add_argument('--csv', action='store_true', help='Gerar em formato CSV')
    parser.add_argument('--output', type=str, help='Arquivo de saída (CSV)')
    parser.add_argument('--fast', action='store_true', help='Usar aproximação rápida (menos preciso)')

    args = parser.parse_args()

    use_real_tokens = not args.fast

    if args.csv or args.output:
        generate_csv(args.days, args.output)
    else:
        generate_simple_table(args.days, use_real_tokenization=use_real_tokens)


if __name__ == '__main__':
    main()
