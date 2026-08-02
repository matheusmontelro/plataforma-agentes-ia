# backend/main.py
import os
import secrets

from fastapi import Cookie, FastAPI, Header, HTTPException, Depends, Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware
from typing import Optional
from backend.auth import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    AuthenticationInfrastructureError,
    REFRESH_TOKEN_EXPIRE_DAYS,
    authenticate_login_and_issue_tokens,
    refresh_access_token,
    run_http_auth_off_loop,
    shutdown_auth_executors,
)
from backend.db import (
    SessionLocal,
    check_database_connection,
    get_connection_stats,
    get_db,
    mark_session_as_web_request,
)
from backend.health_checks import probe_database_health
from backend.memory_tracker import memory_tracker
import psutil
import gc
import sys
from collections import defaultdict
from sqlalchemy.orm import Session
from sqlalchemy.exc import OperationalError, TimeoutError as SQLAlchemyTimeoutError
from backend.models import Client, Company, Team, User
from backend.logging_config import logger
from backend.metrics import REQUEST_COUNT, REQUEST_LATENCY
from backend.security import SecurityHeadersMiddleware, auth_rate_limiter, get_allowed_hosts
import time
import asyncio
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
from backend.routes.chat_ws import chat_router
from backend.routes.media_routes import router as media_router
from backend.routes import prompt_config, webhook, company
from backend.routes.account_profile_routes import router as account_profile_router
from fastapi.security import OAuth2PasswordRequestForm
from backend.routes.integrations.calendar_integration import router as calendar_router
from backend.routes.integrations.support_group_integration import router as support_group_router
from backend.routes.integrations.telegram_integration import router as telegram_integration_router
from backend.routes import agendamento_routes
from backend.routes import arquivos, waha_media
from backend.routes import followups
from backend.ws_manager import start_manager, stop_manager
from backend.routes import followup_schedule
from backend.routes.confirmation_routes import router as confirmation_router
from backend.routes.confirmation_schedule import router as confirmation_schedule_router
from backend.routes import leads_routes
from backend.routes import lead_custom_fields_routes
from backend.routes.comparecimentos_routes import router as comparecimentos_router
from backend.routes.vendas_routes import router as vendas_router
# Revenue Management System (ChartMogul-inspired)
from backend.routes.plans_routes import router as plans_router
from backend.routes.contracts_routes import router as contracts_router
from backend.routes.invoices_routes import router as invoices_router
from backend.routes.payments_routes import router as payments_router
from backend.routes.revenue_metrics_routes import router as revenue_metrics_router
from backend.routes.customer_management_routes import router as customer_management_router
from backend.routes.noshow_followup import router as noshow_followup_router
from backend.routes.noshow_followup_schedule import router as noshow_followup_schedule_router
from backend.routes.metrics_funnels import router as metrics_funnels_router
from backend.routes.atendimento import router as atendimento_router
from backend.routes.users import router as users_router
from backend.routes.teams import router as teams_router
from backend.routes.teams import build_user_permissions_payload
from backend.routes.no_show_routes import router as no_show_router
from backend.routes.business_types import router as business_types_router
from backend.routes.ai_windows import ai_windows_router
from backend.routes.chat_optimized import optimized_router
from backend.routes import ad_campaign_routes

from backend.routes.integrations import clinicorp_api # <-- Corrigido
from backend.routes import nps_routes
from backend.routes import waha_routes
from backend.routes.contacts_import import router as contacts_import_router
from backend.routes.contact_archive import router as contact_archive_router
from backend.routes.contact_tasks import router as contact_tasks_router
from backend.routes.contact_notes import router as contact_notes_router
from backend.routes import flow_control
from backend.routes import call_routes
from backend.routes.pos_consulta_followup_routes import router as pos_consulta_followup_router
from backend.routes.pos_venda_followup_routes import router as pos_venda_followup_router
from backend.routes.nutrition_campaign_routes import router as nutrition_campaign_router
from backend.routes.public import company_setup_router
from backend.routers.referral_campaigns import router as referral_campaigns_router
from backend.routes.agent_workforces import router as agent_workforces_router
from backend.routes.agents_sdk_routes import router as agents_sdk_router
from backend.routes.ai_credits_routes import router as ai_credits_router
from backend.routes.ai_provider_routes import router as ai_provider_router
from backend.routes.password_reset_routes import router as password_reset_router
from backend.services.company_access_control import (
    CompanyOperationalLockBusyError,
    IdentityOperationBusyError,
    normalize_account_email,
)

from backend.routes.whatsapp_campaign_routes import router as whatsapp_campaign_routes_router

# Meta Conversions API


ENVIRONMENT = os.getenv("ENVIRONMENT", "production").lower()
COOKIE_SECURE = os.getenv("AUTH_COOKIE_SECURE", "true" if ENVIRONMENT == "production" else "false").lower() == "true"
COOKIE_SAMESITE = os.getenv("AUTH_COOKIE_SAMESITE", "lax").lower()
CSRF_COOKIE_NAME = "csrf_token"
CSRF_HEADER_NAME = "x-csrf-token"
AUTH_LOGIN_RATE_LIMIT = int(os.getenv("AUTH_LOGIN_RATE_LIMIT", "10"))
AUTH_LOGIN_RATE_WINDOW_SECONDS = int(os.getenv("AUTH_LOGIN_RATE_WINDOW_SECONDS", "300"))
AUTH_REFRESH_RATE_LIMIT = int(os.getenv("AUTH_REFRESH_RATE_LIMIT", "120"))
AUTH_REFRESH_RATE_WINDOW_SECONDS = int(os.getenv("AUTH_REFRESH_RATE_WINDOW_SECONDS", "300"))
AUTH_BUSY_MESSAGE = "Serviço temporariamente indisponível. Tente novamente em instantes."

app = FastAPI(
    docs_url=None if ENVIRONMENT == "production" else "/docs",
    redoc_url=None if ENVIRONMENT == "production" else "/redoc",
    openapi_url=None if ENVIRONMENT == "production" else "/openapi.json",
)


async def transient_lock_busy_exception_handler(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    """Expose bounded lock contention as retryable instead of a generic 500."""
    del request
    retry_after_seconds = max(
        1,
        int(getattr(exc, "retry_after_seconds", 2)),
    )
    return JSONResponse(
        status_code=503,
        content={"detail": AUTH_BUSY_MESSAGE},
        headers={"Retry-After": str(retry_after_seconds)},
    )


app.add_exception_handler(
    CompanyOperationalLockBusyError,
    transient_lock_busy_exception_handler,
)
app.add_exception_handler(
    IdentityOperationBusyError,
    transient_lock_busy_exception_handler,
)
app.add_exception_handler(
    AuthenticationInfrastructureError,
    transient_lock_busy_exception_handler,
)


async def database_operational_error_handler(
    request: Request,
    exc: OperationalError,
) -> JSONResponse:
    """Sanitize lock-timeout and other transient database availability errors."""
    del request
    original = getattr(exc, "orig", None)
    sqlstate = (
        getattr(original, "sqlstate", None)
        or getattr(original, "pgcode", None)
        or "unknown"
    )
    logger.warning(
        "Falha operacional transitória no banco: sqlstate=%s",
        sqlstate,
    )
    return JSONResponse(
        status_code=503,
        content={"detail": AUTH_BUSY_MESSAGE},
        headers={"Retry-After": "1" if sqlstate == "55P03" else "2"},
    )


app.add_exception_handler(OperationalError, database_operational_error_handler)
app.add_exception_handler(SQLAlchemyTimeoutError, database_operational_error_handler)

allowed_hosts = get_allowed_hosts()
if allowed_hosts and "*" not in allowed_hosts:
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts)

app.add_middleware(SecurityHeadersMiddleware)


@app.middleware("http")
async def legacy_domain_compatibility_middleware(request: Request, call_next):
    """Accept legacy clinic-shaped URLs/query params while the public API migrates."""
    path = request.scope.get("path", "")
    new_path = path
    replacements = (
        ("/client-clinics", "/client-companies"),
        ("/clinics-admin", "/companies-admin"),
        ("/complete-clinic", "/complete-company"),
        ("/clinics/", "/companies/"),
        ("/api/clinic/", "/api/company/"),
        ("/api/clinic", "/api/company"),
        ("/clinic/", "/company/"),
        ("/clinic", "/company"),
    )
    for old, new in replacements:
        new_path = new_path.replace(old, new)
    if new_path != path:
        request.scope["path"] = new_path

    query_string = request.scope.get("query_string", b"")
    if b"clinic_id=" in query_string:
        request.scope["query_string"] = query_string.replace(b"clinic_id=", b"company_id=")

    return await call_next(request)


def set_auth_cookies(response: Response, access_token: str, refresh_token: str) -> str:
    csrf_token = secrets.token_urlsafe(32)
    response.set_cookie(
        "access_token",
        access_token,
        max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite=COOKIE_SAMESITE,
        path="/",
    )
    response.set_cookie(
        "refresh_token",
        refresh_token,
        max_age=REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite=COOKIE_SAMESITE,
        path="/auth",
    )
    response.set_cookie(
        CSRF_COOKIE_NAME,
        csrf_token,
        max_age=REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
        httponly=False,
        secure=COOKIE_SECURE,
        samesite=COOKIE_SAMESITE,
        path="/",
    )
    response.headers["X-CSRF-Token"] = csrf_token
    return csrf_token


def clear_auth_cookies(response: Response) -> None:
    for name, path in (("access_token", "/"), ("refresh_token", "/auth"), (CSRF_COOKIE_NAME, "/")):
        response.delete_cookie(name, path=path, secure=COOKIE_SECURE, samesite=COOKIE_SAMESITE)


def require_monitoring_access(x_monitoring_token: str | None = Header(None)):
    expected = os.getenv("MONITORING_TOKEN")
    if not expected:
        if ENVIRONMENT == "production":
            raise HTTPException(status_code=404, detail="Not found")
        return True
    if not x_monitoring_token or not secrets.compare_digest(x_monitoring_token, expected):
        raise HTTPException(status_code=403, detail="Acesso negado")
    return True


@app.middleware("http")
async def csrf_cookie_middleware(request: Request, call_next):
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        uses_cookie_auth = bool(request.cookies.get("access_token")) and not request.headers.get("authorization")
        if uses_cookie_auth and not request.url.path.startswith(("/auth/login", "/auth/refresh", "/auth/logout")):
            csrf_cookie = request.cookies.get(CSRF_COOKIE_NAME)
            csrf_header = request.headers.get(CSRF_HEADER_NAME)
            if not csrf_cookie or not csrf_header or not secrets.compare_digest(csrf_cookie, csrf_header):
                return JSONResponse(status_code=403, content={"detail": "CSRF token inválido"})

    return await call_next(request)

# Custom middleware to handle CORS for public webhook routes
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response as StarletteResponse

class WebhookCORSMiddleware(BaseHTTPMiddleware):
    """Handle CORS for public webhook trigger endpoints - allows all origins"""
    async def dispatch(self, request, call_next):
        # Only apply to webhook trigger routes
        if request.url.path.startswith("/webhook/trigger/"):
            # Handle preflight OPTIONS request
            if request.method == "OPTIONS":
                return StarletteResponse(
                    content="",
                    status_code=204,
                    headers={
                        "Access-Control-Allow-Origin": "*",
                        "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
                        "Access-Control-Allow-Headers": "Content-Type, Authorization, X-Requested-With",
                        "Access-Control-Max-Age": "86400",
                    }
                )
            # For actual requests, add CORS headers to response
            response = await call_next(request)
            response.headers["Access-Control-Allow-Origin"] = "*"
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
            response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, X-Requested-With"
            return response

        return await call_next(request)

# IMPORTANT: Middleware order is LIFO (last added runs first on request)
# Add standard CORS first, then webhook CORS (so webhook CORS intercepts first)

DEFAULT_CORS_ORIGINS = [
    "http://localhost:3000",
    "http://localhost:3001",
    "http://localhost:3002",
    "http://localhost:3003",
    "http://localhost:3004",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:3004",
]
CORS_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "CORS_ORIGINS",
        ",".join(DEFAULT_CORS_ORIGINS),
    ).split(",")
    if origin.strip()
]

# Standard CORS middleware for authenticated routes (runs SECOND on incoming requests)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Webhook CORS middleware (runs FIRST on incoming requests - intercepts before standard CORS)
app.add_middleware(WebhookCORSMiddleware)

app.include_router(chat_router)
app.include_router(media_router)
app.include_router(prompt_config.router)
app.include_router(webhook.router, prefix="/webhook")
app.include_router(waha_routes.router, prefix="/webhook", tags=["waha"])
app.include_router(waha_routes.router, prefix="/api/waha", tags=["waha-api"])
app.include_router(contacts_import_router, prefix="/webhook", tags=["contacts_import"])
app.include_router(contact_archive_router, prefix="/webhook", tags=["contact_archive"])
app.include_router(contact_tasks_router, prefix="/api", tags=["contact_tasks"])
app.include_router(contact_notes_router, prefix="/api", tags=["contact_notes"])

# Tags System
from backend.routes.tags import router as tags_router
app.include_router(tags_router, prefix="/webhook", tags=["tags"])

app.include_router(company.router, prefix="/api", tags=["company"])
app.include_router(account_profile_router, prefix="/api")
app.include_router(calendar_router, prefix="/api/integrations/calendar", tags=["calendar_integration"])
app.include_router(support_group_router, prefix="/api/integrations/support-group", tags=["support_group_integration"])
app.include_router(telegram_integration_router, prefix="/api/integrations/telegram", tags=["telegram_integration"])
app.include_router(agendamento_routes.router, prefix="/api/agenda")
app.include_router(arquivos.router, prefix="/api/arquivos", tags=["arquivos"])
app.include_router(waha_media.router, prefix="/api/waha", tags=["waha-media"])
app.include_router(followups.router, prefix="/api", tags=["followups"])
app.include_router(followup_schedule.router, prefix="/api", tags=["followup-schedule"])
app.include_router(confirmation_router, prefix="/api", tags=["confirmations"])
app.include_router(confirmation_schedule_router, prefix="/api", tags=["confirmation-schedule"])
app.include_router(lead_custom_fields_routes.router, prefix="/api/agenda")
app.include_router(leads_routes.router, prefix="/api/agenda")
app.include_router(leads_routes.router, prefix="/api") # Also register under /api for general CRM usage
app.include_router(comparecimentos_router, prefix="/api/agenda")
app.include_router(vendas_router, prefix="/api/agenda")

# Revenue Management System (ChartMogul-inspired)
app.include_router(plans_router, prefix="/api")
app.include_router(contracts_router, prefix="/api")
app.include_router(invoices_router, prefix="/api")
app.include_router(payments_router, prefix="/api")
app.include_router(revenue_metrics_router, prefix="/api")
app.include_router(customer_management_router, prefix="/api")

app.include_router(noshow_followup_router, prefix="/api", tags=["no-show-followup"])
app.include_router(noshow_followup_schedule_router, prefix="/api", tags=["no-show-schedule"])
app.include_router(metrics_funnels_router, prefix="/api", tags=["metrics"])
app.include_router(atendimento_router, prefix="/api")
app.include_router(users_router, prefix="/api", tags=["users"])
app.include_router(teams_router, prefix="/api", tags=["teams"])
app.include_router(business_types_router, tags=["Business Types"])
app.include_router(no_show_router, prefix="/api/agenda")
app.include_router(ai_windows_router, prefix="/api", tags=["AI Windows"])
app.include_router(optimized_router, prefix="/api/chat-optimized")
app.include_router(ad_campaign_routes.router, prefix="", tags=["Ad Campaign Metrics"])

app.include_router(clinicorp_api.router, prefix="/api/integrations", tags=["clinicorp_api"]) # <-- Corrigido e prefixo ajustado
app.include_router(nps_routes.router, prefix="/api/nps", tags=["NPS"])
app.include_router(flow_control.router, tags=["Flow Control"])
app.include_router(call_routes.router, prefix="/api", tags=["Call"])
app.include_router(pos_consulta_followup_router, prefix="/api", tags=["pos-consulta-followup"])
app.include_router(pos_venda_followup_router, prefix="/api", tags=["pos-venda-followup"])
app.include_router(nutrition_campaign_router, prefix="/api/nutrition-campaigns", tags=["nutrition-campaigns"])

from backend.routes.media_routes import router as media_routes_router
app.include_router(media_routes_router)

# Media endpoints para servir arquivos de vídeo/áudio/imagem salvos localmente
from backend.routes.media import media_router as local_media_router
app.include_router(local_media_router)

from backend.routes.crm_kanban import router as crm_kanban_router
app.include_router(crm_kanban_router, prefix="/api", tags=["CRM Kanban"])

from backend.routes import webhook_builder
from backend.routes import flow_builder # Added import for flow_builder
from backend.routes import flow_executor # Agent response execution for FlowBuilder
app.include_router(webhook_builder.router, tags=["Webhook Builder"])
app.include_router(flow_builder.router, prefix="/api/flows", tags=["Flow Builder"]) # Novo router
app.include_router(flow_executor.router, prefix="/api/flows", tags=["Flow Executor"])
app.include_router(agent_workforces_router, prefix="/api", tags=["Agent Workforces"])
app.include_router(agents_sdk_router)
app.include_router(ai_credits_router, prefix="/api")
app.include_router(ai_provider_router, prefix="/api")

app.include_router(whatsapp_campaign_routes_router, tags=["WhatsApp Campaigns"])
from backend.routes import calendar_routes
app.include_router(calendar_routes.router, prefix="/api/calendar", tags=["Calendar"])

# Referral Campaigns Router
app.include_router(referral_campaigns_router, prefix="/api", tags=["Referral Campaigns"])

# Rotas públicas (com autenticação por API Key)
app.include_router(company_setup_router, prefix="/api/public/setup", tags=["Public Setup"])
app.include_router(password_reset_router, prefix="/auth", tags=["password-reset"])

@app.on_event("startup")
async def startup_event():
    await start_manager()

@app.on_event("startup")
def startup_event():
    logger.info("Aplicação iniciando...")

@app.on_event("shutdown")
async def shutdown_event():
    await stop_manager()
    shutdown_auth_executors()
    logger.info("Aplicação encerrando...")

def _authentication_unavailable(exc: Exception) -> HTTPException:
    retry_after_seconds = max(
        1,
        int(getattr(exc, "retry_after_seconds", 2)),
    )
    return HTTPException(
        status_code=503,
        detail=AUTH_BUSY_MESSAGE,
        headers={"Retry-After": str(retry_after_seconds)},
    )


def _authenticate_login_request(
    *,
    email: str,
    password: str,
):
    """Build the complete login result in one worker-owned DB session."""
    from sqlalchemy.orm import joinedload

    db = None
    try:
        db = mark_session_as_web_request(SessionLocal())
        authenticated = authenticate_login_and_issue_tokens(
            db,
            email=email,
            password=password,
            finalize_transaction=False,
        )
        company = (
            db.query(Company)
            .options(joinedload(Company.business_type))
            .filter(Company.id == authenticated.company_id)
            .first()
        )
        business_type_code = (
            company.business_type.code
            if company and company.business_type
            else "business_company"
        )
        settings = dict(company.settings or {}) if company else {}

        if authenticated.user_type == "master":
            account = (
                db.query(Client)
                .filter(Client.id == authenticated.account_id)
                .first()
            )
            if not account:
                raise HTTPException(status_code=401, detail="Usuário inativo")
            permissions_payload = build_user_permissions_payload(db, account)
            user_team = None
        else:
            account = (
                db.query(User)
                .filter(User.id == authenticated.account_id)
                .first()
            )
            if not account:
                raise HTTPException(status_code=401, detail="Usuário inativo")
            permissions_payload = build_user_permissions_payload(db, account)
            user_team = None
            if authenticated.team_id is not None:
                team = (
                    db.query(Team)
                    .filter(Team.id == authenticated.team_id)
                    .first()
                )
                if team:
                    user_team = team.code

        payload = {
            "token_type": "bearer",
            "company_id": authenticated.company_id,
            "clinic_id": authenticated.company_id,
            "client_id": authenticated.client_id,
            "user_type": authenticated.user_type,
            "user_id": authenticated.account_id,
            "team": permissions_payload["team"],
            "sidebar_permissions": permissions_payload["sidebar_permissions"],
            "contact_permissions": permissions_payload["contact_permissions"],
            "business_type": business_type_code,
            "settings": settings,
        }
        if authenticated.user_type == "user":
            payload["user_team"] = user_team

        # Keep authentication, session persistence and response materialization
        # atomic. A payload failure must not leave a committed ghost session.
        payload = jsonable_encoder(payload)
        if authenticated.user_type == "user":
            db.commit()
        else:
            db.rollback()
        return authenticated.tokens, payload
    except (
        AuthenticationInfrastructureError,
        CompanyOperationalLockBusyError,
        HTTPException,
        IdentityOperationBusyError,
    ):
        if db is not None:
            db.rollback()
        raise
    except Exception as exc:
        if db is not None:
            db.rollback()
        logger.error(
            "Falha de infraestrutura ao montar resposta de login: %s",
            exc.__class__.__name__,
        )
        raise AuthenticationInfrastructureError() from None
    finally:
        if db is not None:
            try:
                db.close()
            except Exception as exc:
                logger.warning(
                    "Falha ao encerrar sessão de login: %s",
                    exc.__class__.__name__,
                )


@app.post("/auth/login")
async def login(
    request: Request,
    response: Response,
    form_data: OAuth2PasswordRequestForm = Depends(),
):
    await auth_rate_limiter.check(
        request,
        "auth.login",
        form_data.username,
        limit=AUTH_LOGIN_RATE_LIMIT,
        window_seconds=AUTH_LOGIN_RATE_WINDOW_SECONDS,
    )
    normalized_login_email = normalize_account_email(form_data.username)
    logger.info(f"Recebida requisição de login - Username: {form_data.username}")
    try:
        tokens, payload = await run_http_auth_off_loop(
            _authenticate_login_request,
            email=normalized_login_email,
            password=form_data.password,
        )
    except (
        AuthenticationInfrastructureError,
        CompanyOperationalLockBusyError,
        IdentityOperationBusyError,
    ) as exc:
        raise _authentication_unavailable(exc) from None
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(
            "Erro inesperado ao fazer login: %s",
            exc.__class__.__name__,
        )
        raise _authentication_unavailable(
            AuthenticationInfrastructureError()
        ) from None

    set_auth_cookies(
        response,
        tokens["access_token"],
        tokens["refresh_token"],
    )
    logger.info(
        "Login bem-sucedido (%s) para: %s",
        str(payload["user_type"]).upper(),
        form_data.username,
    )
    return payload

@app.post("/auth/refresh")
async def refresh_token_endpoint(
    request: Request,
    response: Response,
    refresh_token: str | None = None,
    refresh_token_cookie: str | None = Cookie(None, alias="refresh_token"),
):
    logger.info("Tentativa de refresh do token")
    await auth_rate_limiter.check(
        request,
        "auth.refresh",
        None,
        limit=AUTH_REFRESH_RATE_LIMIT,
        window_seconds=AUTH_REFRESH_RATE_WINDOW_SECONDS,
    )

    try:
        refresh_token = refresh_token or refresh_token_cookie
        if not refresh_token:
            raise HTTPException(status_code=401, detail="Refresh token não fornecido")

        # Usa a nova função refresh_access_token que faz toda a validação
        tokens = await run_http_auth_off_loop(refresh_access_token, refresh_token)
        set_auth_cookies(response, tokens["access_token"], tokens["refresh_token"])
        logger.info("Refresh de token bem-sucedido")
        return {"token_type": "bearer", "refreshed": True}

    except (
        AuthenticationInfrastructureError,
        CompanyOperationalLockBusyError,
        IdentityOperationBusyError,
    ) as exc:
        raise _authentication_unavailable(exc) from None
    except HTTPException as exc:
        logger.warning(
            "Erro de autenticação no refresh do token: status=%s",
            exc.status_code,
        )
        raise

    except Exception as exc:
        logger.error(
            "Erro inesperado ao fazer refresh do token: %s",
            exc.__class__.__name__,
        )
        raise _authentication_unavailable(
            AuthenticationInfrastructureError()
        ) from None


@app.post("/auth/logout")
async def logout(response: Response):
    clear_auth_cookies(response)
    return {"message": "Logout realizado com sucesso"}

# Middleware de logs e métricas
@app.middleware("http")
async def log_and_metrics_middleware(request: Request, call_next):
    start_time = time.time()
    endpoint = request.url.path
    method = request.method
    logger.info(f"Nova requisição: {method} {endpoint}")
    REQUEST_COUNT.labels(method=method, endpoint=endpoint).inc()
    try:
        response: Response = await call_next(request)
    except Exception as e:
        logger.error(f"Erro ao processar {method} {endpoint}: {e}")
        raise
    latency = time.time() - start_time
    REQUEST_LATENCY.labels(method=method, endpoint=endpoint).observe(latency)
    logger.info(f"Resposta: {response.status_code} para {method} {endpoint} (latência: {latency:.4f}s)")
    return response

@app.get("/metrics", include_in_schema=False)
def metrics(_: bool = Depends(require_monitoring_access)):
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

@app.get("/health/db-connections", include_in_schema=False)
def db_connection_health(_: bool = Depends(require_monitoring_access)):
    """Monitora o pool e confirma que o banco executa uma consulta real."""
    stats = get_connection_stats()
    payload, error_type = probe_database_health(
        stats,
        check_connection=check_database_connection,
        timestamp=time.time(),
    )
    if error_type is not None:
        logger.warning("Health check do banco falhou (%s)", error_type)
        return JSONResponse(status_code=503, content=payload)
    return payload

@app.get("/health/memory", include_in_schema=False)
def memory_health(_: bool = Depends(require_monitoring_access)):
    """Endpoint para monitorar uso detalhado de memória"""
    process = psutil.Process()

    # Informações básicas do processo
    memory_info = process.memory_info()
    memory_percent = process.memory_percent()

    # Análise detalhada de objetos Python
    gc.collect()  # Force garbage collection

    # Contar objetos por tipo
    obj_counts = defaultdict(int)
    obj_sizes = defaultdict(int)

    for obj in gc.get_objects():
        obj_type = type(obj).__name__
        obj_counts[obj_type] += 1
        try:
            obj_sizes[obj_type] += sys.getsizeof(obj)
        except:
            pass

    # Top 10 tipos de objetos por quantidade
    top_objects_by_count = dict(sorted(obj_counts.items(), key=lambda x: x[1], reverse=True)[:10])

    # Top 10 tipos de objetos por tamanho
    top_objects_by_size = dict(sorted(obj_sizes.items(), key=lambda x: x[1], reverse=True)[:10])

    # Informações do sistema
    system_memory = psutil.virtual_memory()

    return {
        "process": {
            "rss_mb": round(memory_info.rss / 1024 / 1024, 2),
            "vms_mb": round(memory_info.vms / 1024 / 1024, 2),
            "percent": round(memory_percent, 2),
            "threads": process.num_threads(),
            "connections": len(process.connections()),
            "open_files": len(process.open_files())
        },
        "system": {
            "total_mb": round(system_memory.total / 1024 / 1024, 2),
            "available_mb": round(system_memory.available / 1024 / 1024, 2),
            "used_percent": system_memory.percent
        },
        "python_objects": {
            "total_objects": len(gc.get_objects()),
            "top_by_count": top_objects_by_count,
            "top_by_size": {k: round(v / 1024 / 1024, 2) for k, v in top_objects_by_size.items()}
        },
        "garbage_collector": {
            "collections": gc.get_stats(),
            "uncollectable": len(gc.garbage)
        },
        "module_tracking": {
            "top_consumers": memory_tracker.get_top_consumers(10),
            "all_modules": memory_tracker.get_module_stats()
        },
        "timestamp": time.time()
    }

@app.get("/health/memory-modules", include_in_schema=False)
def memory_modules(_: bool = Depends(require_monitoring_access)):
    """Endpoint específico para monitoramento de módulos"""
    return {
        "current_memory_mb": memory_tracker.get_current_memory(),
        "top_consumers": memory_tracker.get_top_consumers(15),
        "module_details": memory_tracker.get_module_stats(),
        "timestamp": time.time()
    }

@app.get("/")
def read_root():
    return {"message": "API Online"}
