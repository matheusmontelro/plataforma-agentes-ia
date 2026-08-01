#!/usr/bin/env python3
"""
Script CLI para análise de mensagens por empresa

Uso:
    python run_analysis.py --company-id 2
    python run_analysis.py --company-id 2 --days 90
    python run_analysis.py --all
    python run_analysis.py --company-id 2 --detailed
    python run_analysis.py --company-id 2 --output report.txt
"""

import sys
import argparse
import json
from datetime import datetime, timedelta
from pathlib import Path

# Adiciona o diretório raiz do projeto ao path
project_root = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from backend.db import get_db
from backend.agents_sdk.analytics import MessageAnalytics


def format_number(num):
    """Formata número com separador de milhares"""
    return f"{num:,.0f}".replace(",", ".")


def print_company_stats(company_id, stats):
    """Imprime estatísticas de uma empresa de forma formatada"""
    print(f"\n{'='*70}")
    print(f"  ANÁLISE DE MENSAGENS - EMPRESA {company_id}")
    print(f"{'='*70}")

    period = stats['period']
    total = stats['total']
    daily = stats['daily_average']
    monthly = stats['monthly_projection']

    print(f"\n📅 PERÍODO: {period['start'][:10]} a {period['end'][:10]} ({period['days']} dias)")

    print(f"\n📊 TOTAIS NO PERÍODO:")
    print(f"   Mensagens:        {format_number(total['messages']):>15}")
    print(f"   Caracteres:       {format_number(total['characters']):>15}")
    print(f"   Tokens estimados: {format_number(total['estimated_tokens']):>15}")

    print(f"\n📈 MÉDIA DIÁRIA:")
    print(f"   Mensagens/dia:    {daily['messages']:>15.2f}")
    print(f"   Caracteres/dia:   {daily['characters']:>15.2f}")
    print(f"   Tokens/dia:       {daily['tokens']:>15.2f}")

    print(f"\n🗓️  PROJEÇÃO MENSAL (30 dias):")
    print(f"   Mensagens/mês:    {format_number(monthly['messages']):>15}")
    print(f"   Caracteres/mês:   {format_number(monthly['characters']):>15}")
    print(f"   Tokens/mês:       {format_number(monthly['tokens']):>15}")

    print(f"\n💰 CUSTO ESTIMADO MENSAL:")
    print(f"   USD:              $ {monthly['estimated_cost_usd']:>13.2f}")
    print(f"   BRL:              R$ {monthly['estimated_cost_brl']:>12.2f}")

    print(f"\n{'='*70}\n")


def print_detailed_analysis(analysis):
    """Imprime análise detalhada com tokenização real"""
    print(f"\n{'='*70}")
    print(f"  ANÁLISE DETALHADA COM TOKENIZAÇÃO REAL - EMPRESA {analysis['company_id']}")
    print(f"{'='*70}")

    period = analysis['period']
    sample = analysis['sample_analysis']
    totals = analysis['period_totals']
    monthly = analysis['monthly_projection']

    print(f"\n📅 PERÍODO: {period['start'][:10]} a {period['end'][:10]} ({period['days']} dias)")

    print(f"\n🔬 ANÁLISE DA AMOSTRA:")
    print(f"   Tamanho da amostra:           {sample['sample_size']:>10,}")
    print(f"   Total de mensagens no período: {sample['total_messages_in_period']:>10,}")
    print(f"   Média tokens/mensagem:        {sample['avg_tokens_per_message']:>10.2f}")
    print(f"   Média caracteres/mensagem:    {sample['avg_chars_per_message']:>10.2f}")
    print(f"   Caracteres por token:         {sample['chars_per_token']:>10.2f}")

    print(f"\n📊 TOTAIS DO PERÍODO:")
    print(f"   Mensagens:                    {totals['messages']:>10,}")
    print(f"   Tokens estimados:             {format_number(totals['estimated_tokens']):>15}")
    print(f"   Média diária (mensagens):     {totals['daily_avg_messages']:>10.2f}")
    print(f"   Média diária (tokens):        {totals['daily_avg_tokens']:>10.2f}")

    print(f"\n🗓️  PROJEÇÃO MENSAL (30 dias):")
    print(f"   Mensagens/mês:                {format_number(monthly['messages']):>15}")
    print(f"   Tokens/mês:                   {format_number(monthly['tokens']):>15}")

    print(f"\n💰 CUSTO ESTIMADO MENSAL:")
    print(f"   USD:                          $ {monthly['estimated_cost_usd']:>13.2f}")
    print(f"   BRL:                          R$ {monthly['estimated_cost_brl']:>12.2f}")

    print(f"\n{'='*70}\n")


def print_all_companies_summary(summary):
    """Imprime resumo de todas as empresas"""
    print(f"\n{'='*70}")
    print(f"  RESUMO CONSOLIDADO - TODAS AS EMPRESAS")
    print(f"{'='*70}")

    print(f"\n🏥 VISÃO GERAL:")
    print(f"   Total de empresas:            {summary['total_companies']:>10}")

    if summary.get('period'):
        period = summary['period']
        print(f"   Período:                      {period['start'][:10]} a {period['end'][:10]}")

    totals = summary['totals']
    print(f"   Mensagens no período:         {format_number(totals['messages_in_period']):>15}")

    print(f"\n🗓️  PROJEÇÃO MENSAL CONSOLIDADA:")
    print(f"   Tokens/mês:                   {format_number(totals['monthly_projected_tokens']):>15}")
    print(f"   Custo estimado:               R$ {totals['monthly_projected_cost_brl']:>12.2f}")

    print(f"\n🏆 TOP 10 EMPRESAS POR VOLUME:\n")

    for i, company in enumerate(summary['ranking'], 1):
        company_id = company['company_id']
        messages = company['monthly_messages']
        cost = company['monthly_cost_brl']
        print(f"   {i:>2}. Empresa {company_id:<6} | {format_number(messages):>12} msgs/mês | R$ {cost:>8.2f}/mês")

    print(f"\n{'='*70}\n")


def main():
    parser = argparse.ArgumentParser(
        description='Análise de mensagens enviadas pela IA por empresa',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemplos de uso:
  %(prog)s --company-id 2
  %(prog)s --company-id 2 --days 90
  %(prog)s --all
  %(prog)s --company-id 2 --detailed
  %(prog)s --company-id 2 --output report.txt
  %(prog)s --all --json
        """
    )

    parser.add_argument(
        '--company-id',
        type=int,
        help='ID da empresa para análise (padrão: todas)'
    )

    parser.add_argument(
        '--days',
        type=int,
        default=30,
        help='Número de dias para análise (padrão: 30)'
    )

    parser.add_argument(
        '--all',
        action='store_true',
        help='Analisar todas as empresas e mostrar resumo'
    )

    parser.add_argument(
        '--detailed',
        action='store_true',
        help='Análise detalhada com tokenização real (apenas com --company-id)'
    )

    parser.add_argument(
        '--json',
        action='store_true',
        help='Saída em formato JSON'
    )

    parser.add_argument(
        '--output',
        type=str,
        help='Arquivo para salvar o relatório'
    )

    args = parser.parse_args()

    # Validações
    if args.detailed and not args.company_id:
        parser.error("--detailed requer --company-id")

    if args.company_id and args.all:
        parser.error("--company-id e --all são mutuamente exclusivos")

    # Conecta ao banco
    try:
        db = next(get_db())
    except Exception as e:
        print(f"❌ Erro ao conectar ao banco de dados: {e}", file=sys.stderr)
        return 1

    # Calcula período
    end_date = datetime.now()
    start_date = end_date - timedelta(days=args.days)

    # Cria analytics
    analytics = MessageAnalytics(db)

    try:
        if args.detailed:
            # Análise detalhada
            result = analytics.get_detailed_token_analysis(
                company_id=args.company_id,
                start_date=start_date,
                end_date=end_date
            )

            if args.json:
                print(json.dumps(result, indent=2, ensure_ascii=False))
            else:
                print_detailed_analysis(result)

            if args.output:
                with open(args.output, 'w', encoding='utf-8') as f:
                    json.dump(result, f, indent=2, ensure_ascii=False)
                print(f"✅ Resultado salvo em: {args.output}")

        elif args.all:
            # Todas as empresas
            result = analytics.get_all_companies_summary(
                start_date=start_date,
                end_date=end_date
            )

            if args.json:
                print(json.dumps(result, indent=2, ensure_ascii=False))
            else:
                print_all_companies_summary(result)

            if args.output:
                with open(args.output, 'w', encoding='utf-8') as f:
                    json.dump(result, f, indent=2, ensure_ascii=False)
                print(f"✅ Resultado salvo em: {args.output}")

        elif args.company_id:
            # Empresa específica
            result = analytics.get_messages_stats_by_company(
                company_id=args.company_id,
                start_date=start_date,
                end_date=end_date
            )

            if not result:
                print(f"❌ Nenhum dado encontrado para empresa {args.company_id}")
                return 1

            if args.json:
                print(json.dumps(result, indent=2, ensure_ascii=False))
            else:
                print_company_stats(args.company_id, result[args.company_id])

            if args.output:
                # Salva relatório formatado
                report = analytics.export_analysis_report(
                    company_id=args.company_id,
                    start_date=start_date,
                    end_date=end_date,
                    output_file=args.output
                )
                print(f"✅ Relatório salvo em: {args.output}")

        else:
            parser.error("Especifique --company-id ou --all")

    except Exception as e:
        print(f"❌ Erro durante análise: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1
    finally:
        db.close()

    return 0


if __name__ == '__main__':
    sys.exit(main())
