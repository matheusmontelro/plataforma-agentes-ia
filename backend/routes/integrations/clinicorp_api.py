
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload, selectinload
from pydantic import BaseModel, Field # Adicionar Field se necessário
from typing import List, Dict, Any, Optional

from backend.db import get_db
from backend.models import CalendarIntegration, ClinicorpDetails, Company # Importar modelos necessários
from backend.routes.integrations.clinicorp_service import get_clinicorp_business_units, get_clinicorp_professionals  # Importar funções do serviço
from backend.logging_config import logger

router = APIRouter(
    # Você pode definir o prefixo aqui ou ao incluir o router em main.py
    # prefix="/api/integrations", # Exemplo se definido aqui
    tags=["clinicorp_api"] # Mantém a tag para organização
)

# --- Modelos Pydantic para as novas rotas ---

class ClinicorpBusinessItem(BaseModel):
    """Representa uma empresa retornada pela API Clinicorp para seleção."""
    id: int
    Name: str # Nome principal ou fantasia

    class Config:
        orm_mode = True # Ou use from_attributes=True em Pydantic V2

class ClinicorpUserItem(BaseModel):
    """Representa um usuário/profissional retornado pela API Clinicorp para seleção."""
    id: int
    name: str # <-- Alterado de FullName para name (conforme schema /professional/list_all_professionals)

    class Config:
        from_attributes = True # Pydantic V2 style

class SelectableDetailsResponse(BaseModel):
    """Resposta da rota que busca opções selecionáveis."""
    businesses: List[ClinicorpBusinessItem] = []
    users: List[ClinicorpUserItem] = []
    message: Optional[str] = None # Para mensagens de aviso se a busca falhar parcialmente

class SelectedDetailsPayload(BaseModel):
    """Corpo da requisição para salvar os IDs selecionados."""
    business_id: int = Field(..., description="ID da Empresa (Business) selecionada pelo usuário no Clinicorp")
    dentist_person_id: int = Field(..., description="ID do Profissional (Person) selecionado pelo usuário no Clinicorp")

class SuccessResponse(BaseModel):
    """Resposta padrão de sucesso."""
    message: str = "Operação realizada com sucesso."


# --- Função Auxiliar Interna ---
def _get_integration_and_creds(company_id: int, db: Session) -> tuple[CalendarIntegration, str, str]:
    """Busca a integração Clinicorp e retorna o objeto, subscriber_id e api_token."""
    integration = db.query(CalendarIntegration).filter(
        CalendarIntegration.company_id == company_id,
        CalendarIntegration.provider == 'clinicorp'
    ).first()

    if not integration:
        logger.warning(f"Helper: Integração Clinicorp para company_id {company_id} não encontrada.")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Integração Clinicorp não configurada para esta empresa."
        )

    subscriber_id = integration.clinicorp_subscriber_id
    api_token = integration.clinicorp_password # Assumindo que o token está aqui

    if not subscriber_id or not api_token:
        logger.error(f"Helper: Integração Clinicorp (ID: {integration.id}) está incompleta (sem subscriber_id ou api_token/password).")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Configuração da integração Clinicorp incompleta (faltando Subscriber ID ou Token API/password)."
        )

    return integration, subscriber_id, api_token


# --- Novas Rotas ---

@router.get(
    "/clinicorp/{company_id}/selectable_details",
    response_model=SelectableDetailsResponse,
    summary="Busca Opções Selecionáveis no Clinicorp",
    description="Busca a lista de empresas (businesses) e profissionais " # <-- Texto atualizado
                "da API Clinicorp para permitir a seleção pelo usuário no frontend.",
)
def get_selectable_clinicorp_details(company_id: int, db: Session = Depends(get_db)):
    logger.info(f"Buscando detalhes selecionáveis Clinicorp para company_id: {company_id}")
    integration, subscriber_id, api_token = _get_integration_and_creds(company_id, db)

    businesses_list: List[ClinicorpBusinessItem] = []
    users_list: List[ClinicorpUserItem] = [] # Usará o modelo atualizado ClinicorpUserItem
    errors = []

    # Buscar Business Units (sem alteração na lógica aqui)
    try:
        businesses_raw = get_clinicorp_business_units(subscriber_id, api_token=api_token)
        for business in businesses_raw:
            try:
                if business.get("id") is not None and business.get("Name"):
                     businesses_list.append(ClinicorpBusinessItem(id=business["id"], Name=business["Name"]))
            except Exception as parse_err:
                 logger.warning(f"Erro ao parsear business item: {business}. Erro: {parse_err}")
        if not businesses_list and businesses_raw:
            errors.append("Nenhuma empresa válida (com ID e Nome) encontrada na resposta do Clinicorp.")
        elif not businesses_raw:
             errors.append("Nenhuma empresa encontrada na resposta do Clinicorp.")


    except HTTPException as e:
        logger.error(f"Erro ao buscar Business Units: {e.detail}")
        errors.append(f"Erro ao buscar empresas: {e.detail}")
    except Exception as e:
         logger.exception(f"Erro inesperado ao buscar Business Units: {e}")
         errors.append("Erro inesperado ao buscar empresas.")

    # Buscar Users/Professionals
    try:
        # Chama a nova função do serviço
        professionals_raw = get_clinicorp_professionals(subscriber_id, api_token=api_token)
        # Itera sobre a lista retornada diretamente
        for professional in professionals_raw:
            try:
                 # Usa o campo 'name' conforme o novo schema
                 if professional.get("id") is not None and professional.get("name"):
                      # Cria o item usando o modelo Pydantic atualizado
                      users_list.append(ClinicorpUserItem(id=professional["id"], name=professional["name"]))
                 elif professional.get("id") is not None and professional.get("FullName"):
                     # Fallback caso a API ainda retorne FullName em algum caso
                     logger.warning(f"Profissional ID {professional.get('id')} retornou 'FullName' em vez de 'name'. Usando FullName.")
                     users_list.append(ClinicorpUserItem(id=professional["id"], name=professional["FullName"]))
            except Exception as parse_err:
                 logger.warning(f"Erro ao parsear professional item: {professional}. Erro: {parse_err}")
        if not users_list and professionals_raw:
             errors.append("Nenhum profissional válido (com ID e Nome) encontrado na resposta do Clinicorp.")
        elif not professionals_raw:
             errors.append("Nenhum profissional encontrado na resposta do Clinicorp.")

    except HTTPException as e:
        logger.error(f"Erro ao buscar Profissionais do Clinicorp: {e.detail}")
        errors.append(f"Erro ao buscar profissionais: {e.detail}")
    except Exception as e:
        logger.exception(f"Erro inesperado ao buscar Profissionais: {e}")
        errors.append("Erro inesperado ao buscar profissionais.")
    # --- Fim Bloco Atualizado ---


    # Retorna as listas (podem estar vazias se houve erro) e uma mensagem de aviso se necessário
    return SelectableDetailsResponse(
        businesses=businesses_list,
        users=users_list, # Nome da chave na resposta ainda é 'users' para consistência
        message="Atenção: Houve erros ao buscar alguns dados do Clinicorp. Verifique os logs." if errors else None
    )


@router.post(
    "/clinicorp/{company_id}/save_selected_details",
    response_model=SuccessResponse,
    summary="Salva os IDs Clinicorp Selecionados",
    description="Recebe os IDs de Business e Dentist Person selecionados pelo usuário "
                "e os salva na tabela clinicorp_details.",
    status_code=status.HTTP_200_OK # Retorna 200 em sucesso
)
def save_selected_clinicorp_details(
    company_id: int,
    payload: SelectedDetailsPayload, # Corpo da requisição com os IDs selecionados
    db: Session = Depends(get_db)
):
    """
    Endpoint para o frontend chamar APÓS o usuário selecionar
    a empresa e o profissional desejados nas listas.
    """
    logger.info(f"Salvando detalhes selecionados Clinicorp para company_id: {company_id}. Payload: {payload}")
    integration, _, _ = _get_integration_and_creds(company_id, db) # Só precisamos do integration.id aqui

    try:
        # Tenta encontrar um registro existente ou cria um novo
        details = db.query(ClinicorpDetails).filter(
            ClinicorpDetails.calendar_integration_id == integration.id
        ).with_for_update().first() # Lock otimista

        if not details:
            details = ClinicorpDetails(calendar_integration_id=integration.id)
            db.add(details)
            logger.info(f"Criando nova entrada em clinicorp_details para integration ID {integration.id}")

        # Atualiza com os IDs recebidos do frontend
        details.business_id = payload.business_id
        details.dentist_person_id = payload.dentist_person_id

        db.commit()
        logger.info(f"Detalhes selecionados Clinicorp (Business: {payload.business_id}, Dentist: {payload.dentist_person_id}) salvos para integration ID {integration.id}")

        return SuccessResponse(message="Detalhes da integração Clinicorp salvos com sucesso!")

    except Exception as e:
        db.rollback()
        logger.exception(f"Erro ao salvar detalhes selecionados Clinicorp no DB para integration ID {integration.id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Erro interno ao salvar os detalhes selecionados no banco de dados."
        )

# --- Rota Antiga (Removida/Comentada) ---
# @router.post(
#     "/clinicorp/{company_id}/sync_details",
#     ...)
# def sync_clinicorp_details(company_id: int, db: Session = Depends(get_db)):
#    # ... (código antigo que salvava o primeiro ID automaticamente) ...
#    pass # Remover ou comentar esta função

# --- Outras rotas existentes (list_users, list_business, etc.) ---
# Se estas rotas devem continuar existindo para outros propósitos,
# lembre-se de adaptar a função _get_integration_and_creds
# ou buscar o token de outra forma para passar ao _make_clinicorp_request
# Exemplo:
# @router.get("/clinicorp/{company_id}/list_business") -> Precisa buscar token e passar pro serviço
# def list_business(company_id: int, db: Session = Depends(get_db)) -> Any:
#      _, subscriber_id, api_token = _get_integration_and_creds(company_id, db)
#      return get_clinicorp_business_units(subscriber_id, api_token=api_token)
# ... (adaptar outras rotas existentes similarmente se necessário) ...
