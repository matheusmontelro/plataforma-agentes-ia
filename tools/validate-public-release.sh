#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

PYTHON_BIN="${PYTHON_BIN:-python3}"
FULL_VALIDATION="${1:-}"
fail() {
  printf 'ERRO: %s\n' "$1" >&2
  exit 1
}

[[ -s LICENSE ]] || fail 'arquivo LICENSE ainda não foi definido'
[[ -f backend/scripts/bootstrap_admin.py ]] || fail 'bootstrap do primeiro administrador ausente'
[[ -f docs/public/README.md ]] || fail 'documentação pública ausente'

tracked_artifacts="$({
  git ls-files | rg -i '(^|/)(\.env$|.*\.(db|sqlite|sqlite3|bin|pem|key|p12|pfx)$|crewai_storage/|frontend/(build|dist)/)' || true
} | rg -v '(^|/)\.env\.[^.]+\.example$' || true)"
if [[ -n "$tracked_artifacts" ]]; then
  printf '%s\n' "$tracked_artifacts" >&2
  fail 'artefatos locais ou sensíveis continuam rastreados'
fi

removed_feature_matches="$(git grep -n -i -E 'support[_-]?chat|support-chat|ThemePreview|/dev/themes|payment[-_ ]?account|bank[-_ ]?account|dados[-_ ]banc[aá]rios|conta de pagamento|checkout[_-]?ready' -- . ':(exclude)tools/validate-public-release.sh' || true)"
if [[ -n "$removed_feature_matches" ]]; then
  printf '%s\n' "$removed_feature_matches" >&2
  fail 'recursos internos removidos continuam rastreados'
fi

commercial_provider_matches="$(git grep -n -i -E 'eduzz|brevo|stripe' -- . ':(exclude)tools/validate-public-release.sh' || true)"
if [[ -n "$commercial_provider_matches" ]]; then
  printf '%s\n' "$commercial_provider_matches" >&2
  fail 'integrações comerciais removidas continuam rastreadas'
fi

[[ ! -e frontend/src/pages/Register.tsx ]] || fail 'tela de autocadastro continua rastreada'
self_registration_matches="$(git grep -n -E '(/auth)?/register([^[:alnum:]_-]|$)' -- . ':(exclude)tools/validate-public-release.sh' || true)"
if [[ -n "$self_registration_matches" ]]; then
  printf '%s\n' "$self_registration_matches" >&2
  fail 'rota ou link de autocadastro continua rastreado'
fi

for env_example in .env.development.example .env.production.example; do
  for smtp_variable in SMTP_HOST SMTP_PORT SMTP_USERNAME SMTP_PASSWORD SMTP_FROM_EMAIL SMTP_FROM_NAME SMTP_STARTTLS; do
    git grep -q "^${smtp_variable}=" -- "$env_example" \
      || fail "variável SMTP ausente de ${env_example}: ${smtp_variable}"
  done
done

tenant_fallback_matches="$(git grep -n -E '(companyId|company_id)[^\n]{0,100}(\|\||\?\?)[^\n]{0,20}[12]([^0-9]|$)|localStorage\.getItem\([^\n]+\)[^\n]{0,40}\|\|[^0-9]{0,5}1([^0-9]|$)' -- '*.py' '*.ts' '*.tsx' || true)"
if [[ -n "$tenant_fallback_matches" ]]; then
  printf '%s\n' "$tenant_fallback_matches" >&2
  fail 'fallback fixo de tenant continua no código público'
fi

phone_matches="$(git grep -n -P '(?<!\d)55(?!00)\d{10,11}(?!\d)' -- '*.py' '*.ts' '*.tsx' '*.js' '*.md' '*.txt' '*.json' || true)"
if [[ -n "$phone_matches" ]]; then
  printf '%s\n' "$phone_matches" >&2
  fail 'telefone plausivelmente real continua em exemplos ou fixtures'
fi

for branding_asset in logo-light.svg logo-dark.svg icon.svg icon-white.svg; do
  [[ -f "frontend/public/branding/$branding_asset" ]] || fail "placeholder de branding ausente: $branding_asset"
done
git grep -q 'SUA_EMPRESA' -- frontend/src/config/branding.ts docs/public/05-personalizacao.md \
  || fail 'placeholder e instruções de branding ausentes'

mapfile -t migrations < <(find backend/alembic/versions -maxdepth 1 -type f -name '*.py' -print)
if [[ "${#migrations[@]}" -ne 1 ]]; then
  fail "esperada exatamente uma migração inicial; encontradas ${#migrations[@]}"
fi

"$PYTHON_BIN" tools/security_check.py
"$PYTHON_BIN" -m compileall -q backend

heads="$({
  ENVIRONMENT=development \
  DATABASE_URL='postgresql://public@127.0.0.1:1/public' \
    "$PYTHON_BIN" -m alembic -c backend/alembic.ini heads
} | sed '/^[[:space:]]*$/d')"
head_count="$(printf '%s\n' "$heads" | wc -l)"
if [[ "$head_count" -ne 1 ]]; then
  printf '%s\n' "$heads" >&2
  fail "esperado exatamente um head Alembic; encontrados $head_count"
fi

if [[ "$FULL_VALIDATION" == '--full' ]]; then
  node tools/check-frontend-audit.mjs
  npm --prefix frontend run typecheck
fi

printf 'OK: edição pública validada (%s)\n' "$(printf '%s' "$heads" | tr -d '\n')"
