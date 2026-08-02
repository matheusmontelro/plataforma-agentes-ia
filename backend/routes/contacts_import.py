import logging
import pandas as pd
import io
from typing import Union, List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from sqlalchemy import text
from pydantic import BaseModel

from ..db import get_db
from ..auth import get_current_user, User, Client
from ..models import Contact, Customer, CustomerManagedCompany, Tag, ContactTag
from ..runtime_settings import CHAT_MEMORY_DIR, CONVERSATIONS_DB_PATH
from ..services.company_access_control import (
    CompanyOperationalLockBusyError,
    CompanyOperationallyBlockedError,
    ensure_company_operational,
    lock_entities_for_mutation,
)

logger = logging.getLogger(__name__)
router = APIRouter()

class ImportResult(BaseModel):
    success: bool
    total_processed: int
    contacts_created: int
    contacts_updated: int
    customers_created: int
    errors: List[str]

class ContactConversionRequest(BaseModel):
    contact_id: int
    action: str  # 'create_lead' ou 'create_customer'
    additional_data: Dict[str, Any] = {}

class LeadConversionRequest(BaseModel):
    source_id: str = "manual_conversion"

class ContactEditRequest(BaseModel):
    name: str

def validate_phone_number(phone: str) -> str:
    """Valida e normaliza número de telefone"""
    # Remove caracteres não numéricos
    clean_phone = ''.join(filter(str.isdigit, phone))

    # Validações básicas
    if len(clean_phone) < 10:
        raise ValueError(f"Telefone muito curto: {phone}")

    if len(clean_phone) > 15:
        raise ValueError(f"Telefone muito longo: {phone}")

    # Normalizar telefone baseado no formato
    if clean_phone.startswith('55'):
        # Já tem código do país, validar formato
        if len(clean_phone) == 13:  # 55 + DDD + 9 dígitos (celular)
            return clean_phone
        elif len(clean_phone) == 12:  # 55 + DDD + 8 dígitos (fixo)
            return clean_phone
        elif len(clean_phone) == 14:  # Possível telefone fixo com DDD duplicado (5500000000000)
            # Verificar se é duplicação: 55 + 21 + 21 + número
            if clean_phone[2:4] == clean_phone[4:6]:  # DDD duplicado
                return clean_phone[:4] + clean_phone[6:]  # Remove a duplicação
            return clean_phone
        else:
            # Formato não reconhecido com 55, manter como está
            return clean_phone
    else:
        # Não tem código do país, adicionar
        if len(clean_phone) == 11:
            # DDD + 9 dígitos (celular)
            return '55' + clean_phone
        elif len(clean_phone) == 10:
            # DDD + 8 dígitos (fixo)
            return '55' + clean_phone
        elif len(clean_phone) == 8:
            # Sem DDD, assumir Rio de Janeiro (21) para compatibilidade
            return '5521' + clean_phone
        else:
            # Outros formatos, assumir que está correto
            return clean_phone

def parse_csv_data(file_content: bytes) -> pd.DataFrame:
    """Parse CSV data from bytes"""
    try:
        # Tentar UTF-8 primeiro
        csv_string = file_content.decode('utf-8')
    except UnicodeDecodeError:
        try:
            # Fallback para latin-1 (Excel)
            csv_string = file_content.decode('latin-1')
        except UnicodeDecodeError:
            # Último recurso: ISO-8859-1
            csv_string = file_content.decode('iso-8859-1')

    # Parse CSV with robust delimiter detection (supports , and ; common in Brazil)
    # dtype=str prevents phone numbers like "5521..." from becoming floats/scientific notation
    df = pd.read_csv(
        io.StringIO(csv_string),
        sep=None,
        engine='python',
        dtype=str,
        skipinitialspace=True,
        index_col=False
    )
    # Fill NaN with empty string
    df = df.fillna('')
    return df

def parse_excel_data(file_content: bytes) -> pd.DataFrame:
    """Parse Excel data from bytes"""
    return pd.read_excel(io.BytesIO(file_content))

@router.post("/contacts/import", response_model=ImportResult)
async def import_contacts(
    file: UploadFile = File(...),
    company_id: int = Form(...),
    user: Union[Client, User] = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Importa contatos de arquivo CSV ou Excel"""

    # Verificar se o usuário tem acesso à empresa
    if hasattr(user, 'company_id') and user.company_id != company_id:
        raise HTTPException(status_code=403, detail="Acesso negado à empresa")

    logger.info(f"Iniciando importação de contatos - Arquivo: {file.filename}, Empresa: {company_id}")

    try:
        # Ler arquivo
        file_content = await file.read()

        # Parse baseado na extensão
        if file.filename.lower().endswith('.csv'):
            df = parse_csv_data(file_content)
        elif file.filename.lower().endswith(('.xls', '.xlsx')):
            df = parse_excel_data(file_content)
        else:
            raise HTTPException(status_code=400, detail="Formato de arquivo não suportado")

        # Validar colunas obrigatórias
        required_columns = ['nome', 'telefone']
        missing_columns = [col for col in required_columns if col not in df.columns]
        if missing_columns:
            raise HTTPException(
                status_code=400,
                detail=f"Colunas obrigatórias ausentes: {', '.join(missing_columns)}"
            )

        # Estatísticas de processamento
        total_processed = len(df)
        contacts_created = 0
        contacts_updated = 0
        customers_created = 0
        errors = []

        logger.info(f"Processando {total_processed} linhas do arquivo")
        logger.info(f"Columns detected: {df.columns.tolist()}")
        if not df.empty:
            logger.info(f"First row sample: {df.iloc[0].to_dict()}")

        # Processar cada linha
        for i, (index, row) in enumerate(df.iterrows()):
            line_num = i + 2
            try:
                # Dados obrigatórios
                nome = str(row['nome']).strip()
                telefone_raw = str(row['telefone']).strip()

                if not nome or not telefone_raw:
                    errors.append(f"Linha {line_num}: Nome e telefone são obrigatórios")
                    continue

                # Validar e normalizar telefone
                try:
                    telefone = validate_phone_number(telefone_raw)
                except ValueError as e:
                    errors.append(f"Linha {line_num}: {str(e)}")
                    continue

                # Dados opcionais
                email = str(row.get('email', '')).strip() if pd.notna(row.get('email')) else None
                observacoes = str(row.get('observacoes', '')).strip() if pd.notna(row.get('observacoes')) else None
                tipo = str(row.get('tipo', 'contato')).strip().lower() if pd.notna(row.get('tipo')) else 'contato'
                tags_raw = str(row.get('tags', '')).strip() if pd.notna(row.get('tags')) else None

                # VERIFICAR SE JÁ EXISTE COMO LEAD OU CLIENTE (não importar duplicatas)
                from ..models import Lead, Customer

                existing_lead = db.query(Lead).filter(
                    Lead.company_id == company_id,
                    Lead.phone == telefone
                ).first()

                existing_customer = db.query(Customer).filter(
                    Customer.company_id == company_id,
                    Customer.telefone == telefone
                ).first()

                if existing_lead or existing_customer:
                    status = "lead" if existing_lead else "cliente"
                    errors.append(f"Linha {line_num}: {nome} ({telefone}) já existe como {status} - ignorado")
                    continue

                # Verificar se contato já existe
                existing_contact = db.query(Contact).filter(
                    Contact.company_id == company_id,
                    Contact.phone == telefone
                ).first()

                contact_to_use = None

                if existing_contact:
                    # Atualizar contato existente
                    existing_contact.name = nome
                    contact_to_use = existing_contact
                    contacts_updated += 1
                    logger.debug(f"Contato atualizado: {nome} ({telefone})")
                else:
                    # Criar novo contato
                    new_contact = Contact(
                        client_id=user.id,
                        company_id=company_id,
                        phone=telefone,
                        name=nome
                    )
                    db.add(new_contact)
                    db.flush()  # Para obter o ID
                    contact_to_use = new_contact
                    contacts_created += 1
                    logger.debug(f"Novo contato criado: {nome} ({telefone})")

                # --- PROCESSAR TAGS ---
                if tags_raw and contact_to_use:
                    try:
                        # Deduplicar nomes de tags na própria linha
                        tag_names = list(set([t.strip() for t in tags_raw.split(',') if t.strip()]))

                        if tag_names:
                            tag_ids_to_link = []
                            for tag_name in tag_names:
                                # Verificar se tag existe
                                tag = db.query(Tag).filter(
                                    Tag.company_id == company_id,
                                    Tag.name == tag_name
                                ).first()

                                if not tag:
                                    # Criar nova tag
                                    tag = Tag(
                                        company_id=company_id,
                                        name=tag_name,
                                        color="#49A5D9"
                                    )
                                    db.add(tag)
                                    db.flush()
                                    logger.info(f"Tag criada import: {tag_name}")

                                tag_ids_to_link.append(tag.id)

                            # Associar tags ao contato
                            # Verificar no banco
                            existing_links = db.query(ContactTag.tag_id).filter(
                                ContactTag.contact_id == contact_to_use.id
                            ).all()
                            existing_ids = {bg[0] for bg in existing_links}

                            for tag_id in tag_ids_to_link:
                                # Verificar no banco E na sessão atual (para evitar duplicatas no mesmo import)
                                # Usamos o session.new para checar o que acabou de ser adicionado mas nao commitado
                                is_in_session = False
                                for new_obj in db.new:
                                    if isinstance(new_obj, ContactTag) and \
                                       new_obj.contact_id == contact_to_use.id and \
                                       new_obj.tag_id == tag_id:
                                        is_in_session = True
                                        break

                                if tag_id not in existing_ids and not is_in_session:
                                    db.add(ContactTag(contact_id=contact_to_use.id, tag_id=tag_id))
                                    existing_ids.add(tag_id)

                    except Exception as e:
                        logger.error(f"Erro tags linha {line_num}: {e}")
                        # Não falha importação por causa de tags

                # SE TIPO = "CLIENTE" (ou "CLIENTE" para compatibilidade), CRIAR AUTOMATICAMENTE NA TABELA CUSTOMERS
                if tipo in ['cliente', 'cliente'] and contact_to_use:
                    try:
                        # Verificar se o usuário existe antes de usá-lo como criado_por
                        criado_por_id = None
                        if hasattr(user, 'id') and user.id:
                            # Verificar se o user.id realmente existe na tabela users
                            user_exists = db.execute(text("SELECT 1 FROM users WHERE id = :user_id"), {"user_id": user.id}).fetchone()
                            if user_exists:
                                criado_por_id = user.id
                            else:
                                logger.warning(f"[IMPORT_CUSTOMERS] User ID {user.id} não existe na tabela users, definindo criado_por como NULL")

                        new_customer = Customer(
                            contact_id=contact_to_use.id,
                            company_id=company_id,
                            nome=nome,
                            telefone=telefone,
                            email=email,
                            observacoes=observacoes,
                            categoria='cliente', # Defaulting to 'cliente'
                            status='ativo',
                            criado_por=criado_por_id
                        )
                        db.add(new_customer)
                        customers_created += 1 # Variable name kept for now or should I rename? I'll keep logic simple.
                        logger.debug(f"Cliente criado automaticamente: {nome}")
                    except Exception as e:
                        errors.append(f"Linha {line_num}: Erro ao criar cliente - {str(e)}")

            except Exception as e:
                errors.append(f"Linha {line_num}: Erro ao processar - {str(e)}")
                logger.error(f"Erro na linha {line_num}: {e}")

        # Commit das alterações
        db.commit()

        result = ImportResult(
            success=True,
            total_processed=total_processed,
            contacts_created=contacts_created,
            contacts_updated=contacts_updated,
            customers_created=customers_created,
            errors=errors
        )

        logger.info(f"Importação concluída - Contatos criados: {contacts_created}, Atualizados: {contacts_updated}, Clientes criados: {customers_created}, Erros: {len(errors)}")

        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erro na importação: {e}", exc_info=True)
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Erro ao processar arquivo: {str(e)}")

@router.post("/contacts/{contact_id}/convert-to-lead")
async def convert_contact_to_lead(
    contact_id: int,
    request_data: LeadConversionRequest = LeadConversionRequest(),
    user: Union[Client, User] = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Converte um contato em lead"""

    logger.info(f"[CONVERT_TO_LEAD] Iniciando conversão - Contact ID: {contact_id}, User ID: {user.id}")

    try:
        # Buscar contato
        contact = db.query(Contact).filter(
            Contact.id == contact_id
        ).first()

        logger.info(f"[CONVERT_TO_LEAD] Contato encontrado: {contact.name if contact else None}")

        # Verificar se usuário tem acesso à empresa do contato
        if hasattr(user, 'company_id') and contact and contact.company_id != user.company_id:
            logger.warning(f"[CONVERT_TO_LEAD] Acesso negado - User company: {user.company_id}, Contact company: {contact.company_id}")
            raise HTTPException(status_code=403, detail="Sem acesso a esta empresa")

        if not contact:
            logger.error(f"[CONVERT_TO_LEAD] Contato {contact_id} não encontrado")
            raise HTTPException(status_code=404, detail="Contato não encontrado")

        # Verificar se já é lead
        from ..models import Lead
        existing_lead = db.query(Lead).filter(
            Lead.company_id == contact.company_id,
            Lead.phone == contact.phone
        ).first()

        if existing_lead:
            contact_photo = getattr(contact, 'photo', None)
            if contact_photo and not existing_lead.thumbnail_url:
                existing_lead.thumbnail_url = contact_photo
                db.commit()
                logger.info(f"[CONVERT_TO_LEAD] Foto do contato vinculada ao lead existente - ID: {existing_lead.id}")

            logger.info(f"[CONVERT_TO_LEAD] Contato já é lead - ID: {existing_lead.id}")
            return {"message": "Contato já é um lead", "lead_id": existing_lead.id}

        # Criar lead
        logger.info(f"[CONVERT_TO_LEAD] Criando novo lead com source_id: {request_data.source_id}")
        new_lead = Lead(
            client_id=str(user.id),
            company_id=contact.company_id,
            name=contact.name,
            phone=contact.phone,
            source_id=request_data.source_id,
            thumbnail_url=getattr(contact, 'photo', None),
            sender_lid=getattr(contact, 'sender_lid', None)
        )

        db.add(new_lead)
        db.commit()
        db.refresh(new_lead)

        logger.info(f"[CONVERT_TO_LEAD] ✅ Contato {contact_id} convertido para lead {new_lead.id}")

        try:
            from backend.services.flow_event_service import trigger_crm_lead_created

            started_flows = trigger_crm_lead_created(db, lead=new_lead, created_at=new_lead.created_at)
            if started_flows:
                logger.info(
                    "[FlowBuilder] %s fluxo(s) lead_created iniciados para contato convertido lead_id=%s",
                    started_flows,
                    new_lead.id,
                )
        except Exception as flow_event_err:
            logger.error(
                "[FlowBuilder] Erro ao iniciar fluxos lead_created para contato convertido lead_id=%s: %s",
                new_lead.id,
                flow_event_err,
            )

        return {
            "success": True,
            "message": "Contato convertido para lead com sucesso",
            "lead_id": new_lead.id
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[CONVERT_TO_LEAD] ❌ Erro na conversão: {e}", exc_info=True)
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Erro ao converter para lead: {str(e)}")

@router.post("/contacts/{contact_id}/convert-to-customer")
async def convert_contact_to_customer(
    contact_id: int,
    user: Union[Client, User] = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Converte um contato em cliente"""

    # Buscar contato
    contact = db.query(Contact).filter(
        Contact.id == contact_id
    ).first()

    # Verificar se usuário tem acesso à empresa do contato
    if hasattr(user, 'company_id') and contact and contact.company_id != user.company_id:
        raise HTTPException(status_code=403, detail="Sem acesso a esta empresa")

    if not contact:
        raise HTTPException(status_code=404, detail="Contato não encontrado")

    # Verificar se já é cliente
    from ..models import Customer
    existing_customer = db.query(Customer).filter(
        Customer.contact_id == contact_id
    ).first()

    if existing_customer:
        return {"message": "Contato já é um cliente", "customer_id": existing_customer.id}

    # Verificar se tem lead associado
    from ..models import Lead
    lead = db.query(Lead).filter(
        Lead.company_id == contact.company_id,
        Lead.phone == contact.phone
    ).first()

    # Verificar se o usuário existe antes de usá-lo como criado_por
    criado_por_id = None
    if hasattr(user, 'id') and user.id:
        # Verificar se o user.id realmente existe na tabela users
        user_exists = db.execute(text("SELECT 1 FROM users WHERE id = :user_id"), {"user_id": user.id}).fetchone()
        if user_exists:
            criado_por_id = user.id
        else:
            logger.warning(f"[CONVERT_TO_CUSTOMER] User ID {user.id} não existe na tabela users, definindo criado_por como NULL")

    # Criar cliente
    new_customer = Customer(
        contact_id=contact_id,
        company_id=contact.company_id,
        nome=contact.name or "Nome não informado",
        telefone=contact.phone,
        convertido_de_lead_id=lead.id if lead else None,
        criado_por=criado_por_id,
        categoria='cliente',
        status='ativo'
    )

    db.add(new_customer)
    db.commit()
    db.refresh(new_customer)

    logger.info(f"Contato {contact_id} convertido para cliente {new_customer.id}")

    return {
        "success": True,
        "message": "Contato convertido para cliente com sucesso",
        "customer_id": new_customer.id
    }

@router.put("/contacts/{contact_id}/edit")
async def edit_contact(
    contact_id: int,
    request_data: ContactEditRequest,
    user: Union[Client, User] = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Edita nome do contato e atualiza em todas as tabelas relacionadas"""

    logger.info(f"[EDIT_CONTACT] Iniciando edição - Contact ID: {contact_id}, Novo nome: {request_data.name}")

    try:
        # Buscar contato
        contact = db.query(Contact).filter(
            Contact.id == contact_id
        ).first()

        if not contact:
            raise HTTPException(status_code=404, detail="Contato não encontrado")

        # Verificar acesso à empresa
        if hasattr(user, 'company_id') and contact.company_id != user.company_id:
            raise HTTPException(status_code=403, detail="Sem acesso a esta empresa")

        old_name = contact.name
        new_name = request_data.name.strip()

        # Atualizar contato
        contact.name = new_name

        # Atualizar lead (se existir)
        from ..models import Lead
        lead = db.query(Lead).filter(
            Lead.company_id == contact.company_id,
            Lead.phone == contact.phone
        ).first()

        if lead:
            lead.name = new_name
            logger.info(f"[EDIT_CONTACT] Lead atualizado - ID: {lead.id}")

        # Atualizar cliente (se existir)
        from ..models import Customer
        customer = db.query(Customer).filter(
            Customer.contact_id == contact_id
        ).first()

        if customer:
            customer.nome = new_name
            logger.info(f"[EDIT_CONTACT] Cliente atualizado - ID: {customer.id}")

        # Atualizar agendamentos
        db.execute(text("""
            UPDATE agendamentos
            SET nome = :new_name
            WHERE company_id = :company_id AND phone = :phone
        """), {
            "new_name": new_name,
            "company_id": contact.company_id,
            "phone": contact.phone
        })

        # Atualizar comparecimentos
        db.execute(text("""
            UPDATE comparecimentos
            SET nome = :new_name
            WHERE company_id = :company_id AND phone = :phone
        """), {
            "new_name": new_name,
            "company_id": contact.company_id,
            "phone": contact.phone
        })

        # Atualizar no-shows
        db.execute(text("""
            UPDATE noshow_events
            SET nome = :new_name
            WHERE company_id = :company_id AND phone = :phone
        """), {
            "new_name": new_name,
            "company_id": contact.company_id,
            "phone": contact.phone
        })

        # Atualizar vendas
        db.execute(text("""
            UPDATE vendas
            SET nome = :new_name
            WHERE company_id = :company_id AND phone = :phone
        """), {
            "new_name": new_name,
            "company_id": contact.company_id,
            "phone": contact.phone
        })

        db.commit()

        logger.info(f"[EDIT_CONTACT] ✅ Nome atualizado de '{old_name}' para '{new_name}' em todas as tabelas")

        return {
            "success": True,
            "message": "Nome atualizado com sucesso em todos os registros",
            "old_name": old_name,
            "new_name": new_name
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[EDIT_CONTACT] ❌ Erro na edição: {e}", exc_info=True)
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Erro ao editar contato: {str(e)}")

@router.delete("/contacts/{contact_id}/delete")
async def delete_contact(
    contact_id: int,
    user: Union[Client, User] = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Exclui contato e TODOS os dados relacionados"""

    logger.info(f"[DELETE_CONTACT] Iniciando exclusão - Contact ID: {contact_id}")

    try:
        # Buscar contato
        contact = db.query(Contact).filter(
            Contact.id == contact_id
        ).first()

        if not contact:
            raise HTTPException(status_code=404, detail="Contato não encontrado")

        # Verificar acesso à empresa
        if hasattr(user, 'company_id') and contact.company_id != user.company_id:
            raise HTTPException(status_code=403, detail="Sem acesso a esta empresa")

        phone = contact.phone
        company_id = contact.company_id

        actor_client_ids = [int(user.id)] if isinstance(user, Client) else []
        actor_user_ids = [int(user.id)] if isinstance(user, User) else []
        lock_entities_for_mutation(
            db,
            company_ids=[company_id],
            client_ids=actor_client_ids,
            user_ids=actor_user_ids,
        )
        try:
            ensure_company_operational(db, company_id)
        except CompanyOperationallyBlockedError as exc:
            raise HTTPException(status_code=423, detail="Acesso suspenso") from exc

        actor_model = Client if isinstance(user, Client) else User if isinstance(user, User) else None
        if actor_model is None:
            raise HTTPException(status_code=403, detail="Acesso negado à empresa")
        actor = (
            db.query(actor_model)
            .filter(actor_model.id == int(user.id))
            .with_for_update()
            .first()
        )
        if (
            not actor
            or not bool(actor.is_active)
            or int(actor.company_id) != int(company_id)
        ):
            raise HTTPException(status_code=423, detail="Acesso suspenso")

        contact = (
            db.query(Contact)
            .filter(
                Contact.id == contact_id,
                Contact.company_id == company_id,
            )
            .with_for_update()
            .first()
        )
        if not contact:
            raise HTTPException(status_code=404, detail="Contato não encontrado")

        linked_workspace = (
            db.query(CustomerManagedCompany.id)
            .join(Customer, Customer.id == CustomerManagedCompany.customer_id)
            .filter(
                CustomerManagedCompany.owner_company_id == company_id,
                Customer.contact_id == contact_id,
            )
            .with_for_update()
            .first()
        )
        if linked_workspace:
            raise HTTPException(
                status_code=409,
                detail="Contato convertido em cliente com workspace vinculado não pode ser excluído",
            )

        # Executar exclusões em cascata (ordem importante)
        # 1. Excluir vendas (FK para comparecimentos)
        result = db.execute(text("""
            DELETE FROM vendas
            WHERE company_id = :company_id AND phone = :phone
        """), {"company_id": company_id, "phone": phone})
        vendas_deleted = result.rowcount

        # 2. Excluir comparecimentos (FK para agendamentos)
        result = db.execute(text("""
            DELETE FROM comparecimentos
            WHERE company_id = :company_id AND phone = :phone
        """), {"company_id": company_id, "phone": phone})
        comparecimentos_deleted = result.rowcount

        # 3. Excluir no-shows (FK para agendamentos)
        result = db.execute(text("""
            DELETE FROM noshow_events
            WHERE company_id = :company_id AND phone = :phone
        """), {"company_id": company_id, "phone": phone})
        noshows_deleted = result.rowcount

        # 4. Excluir agendamentos (FK para leads)
        result = db.execute(text("""
            DELETE FROM agendamentos
            WHERE company_id = :company_id AND phone = :phone
        """), {"company_id": company_id, "phone": phone})
        agendamentos_deleted = result.rowcount

        # 5. Excluir mensagens
        result = db.execute(text("""
            DELETE FROM messages
            WHERE company_id = :company_id AND contact_phone = :phone
        """), {"company_id": company_id, "phone": phone})
        messages_deleted = result.rowcount

        # 6. Primeiro remover a referência do lead nos clientes
        result = db.execute(text("""
            UPDATE customers
            SET convertido_de_lead_id = NULL
            WHERE convertido_de_lead_id IN (
                SELECT id FROM leads
                WHERE company_id = :company_id AND phone = :phone
            )
        """), {"company_id": company_id, "phone": phone})
        customers_updated = result.rowcount

        # 6.1. Agora excluir leads
        result = db.execute(text("""
            DELETE FROM leads
            WHERE company_id = :company_id AND phone = :phone
        """), {"company_id": company_id, "phone": phone})
        leads_deleted = result.rowcount

        # 7. Excluir clientes (FK para contacts)
        result = db.execute(text("""
            DELETE FROM customers
            WHERE contact_id = :contact_id
        """), {"contact_id": contact_id})
        customers_deleted = result.rowcount

        # 8. Excluir contact_tasks (FK para contacts)
        result = db.execute(text("""
            DELETE FROM contact_tasks
            WHERE contact_id = :contact_id
        """), {"contact_id": contact_id})
        tasks_deleted = result.rowcount

        # 8.1. Excluir contact_actions_audit (FK para contacts)
        result = db.execute(text("""
            DELETE FROM contact_actions_audit
            WHERE contact_id = :contact_id
        """), {"contact_id": contact_id})
        audit_deleted = result.rowcount

        # 8.2. Excluir notas do contato (FK para contacts)
        result = db.execute(text("""
            DELETE FROM contact_notes
            WHERE contact_id = :contact_id AND company_id = :company_id
        """), {"contact_id": contact_id, "company_id": company_id})
        notes_deleted = result.rowcount

        # 9. Excluir arquivo chatmemory
        import os
        chatmemory_file = str(CHAT_MEMORY_DIR / f"chatmemory_{company_id}_{phone}.txt")
        chatmemory_deleted = 0
        if os.path.exists(chatmemory_file):
            try:
                os.remove(chatmemory_file)
                chatmemory_deleted = 1
                logger.info(f"[DELETE_CONTACT] Arquivo chatmemory excluído: {chatmemory_file}")
            except Exception as e:
                logger.warning(f"[DELETE_CONTACT] Erro ao excluir chatmemory: {e}")

        # 9.1. Excluir histórico do agents_sdk (SQLite conversations.db)
        import sqlite3
        agents_history_deleted = 0
        try:
            # Session ID format: {phone}_company{company_id} (conforme manager.py:49)
            session_id = f"{phone}_company{company_id}"

            # Conectar ao banco SQLite do agents_sdk (root do projeto, não backend)
            sqlite_path = str(CONVERSATIONS_DB_PATH)
            if os.path.exists(sqlite_path):
                with sqlite3.connect(sqlite_path) as sqlite_conn:
                    cursor = sqlite_conn.cursor()

                    # Primeiro excluir mensagens da sessão
                    cursor.execute("DELETE FROM agent_messages WHERE session_id = ?", (session_id,))
                    messages_deleted = cursor.rowcount

                    # Depois excluir a sessão
                    cursor.execute("DELETE FROM agent_sessions WHERE session_id = ?", (session_id,))
                    sessions_deleted = cursor.rowcount

                    agents_history_deleted = messages_deleted + sessions_deleted

                    sqlite_conn.commit()
                    logger.info(f"[DELETE_CONTACT] Histórico agents_sdk excluído: session_id={session_id}, mensagens={messages_deleted}, sessões={sessions_deleted}")
        except Exception as e:
            logger.warning(f"[DELETE_CONTACT] Erro ao excluir histórico agents_sdk: {e}")

        # 10. Finalmente, excluir contato
        db.delete(contact)

        db.commit()

        logger.info(f"[DELETE_CONTACT] ✅ Exclusão completa - Contact: {contact.name}")
        logger.info(f"[DELETE_CONTACT] Registros excluídos: "
                   f"vendas={vendas_deleted}, comparecimentos={comparecimentos_deleted}, "
                   f"noshows={noshows_deleted}, agendamentos={agendamentos_deleted}, "
                   f"mensagens={messages_deleted}, leads={leads_deleted}, customers={customers_deleted}, "
                   f"tasks={tasks_deleted}, notes={notes_deleted}, audit={audit_deleted}, "
                   f"chatmemory={chatmemory_deleted}, "
                   f"agents_history={agents_history_deleted}")

        return {
            "success": True,
            "message": "Contato e todos os dados relacionados foram excluídos",
            "deleted_records": {
                "vendas": vendas_deleted,
                "comparecimentos": comparecimentos_deleted,
                "noshow_events": noshows_deleted,
                "agendamentos": agendamentos_deleted,
                "messages": messages_deleted,
                "leads": leads_deleted,
                "customers": customers_deleted,
                "contact_tasks": tasks_deleted,
                "contact_notes": notes_deleted,
                "contact_actions_audit": audit_deleted,
                "chatmemory_file": chatmemory_deleted,
                "agents_sdk_history": agents_history_deleted
            }
        }

    except HTTPException:
        db.rollback()
        raise
    except (CompanyOperationalLockBusyError, OperationalError):
        db.rollback()
        raise
    except Exception as e:
        logger.error(f"[DELETE_CONTACT] ❌ Erro na exclusão: {e}", exc_info=True)
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Erro ao excluir contato: {str(e)}")

class CreateContactRequest(BaseModel):
    name: str
    phone: str
    company_id: int

@router.post("/contacts/create")
async def create_contact(
    request_data: CreateContactRequest,
    user: Union[Client, User] = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Cria um novo contato simples"""

    logger.info(f"[CREATE_CONTACT] Iniciando criação - Nome: {request_data.name}, Telefone: {request_data.phone}, Company ID: {request_data.company_id}")

    try:
        # Validar dados
        if not request_data.name.strip():
            raise HTTPException(status_code=400, detail="Nome é obrigatório")

        if not request_data.phone.strip():
            raise HTTPException(status_code=400, detail="Telefone é obrigatório")

        # Normalizar telefone
        logger.info(f"[CREATE_CONTACT] Telefone original: {request_data.phone}")
        try:
            clean_phone = validate_phone_number(request_data.phone)
            logger.info(f"[CREATE_CONTACT] Telefone normalizado: {clean_phone}")
        except ValueError as e:
            logger.error(f"[CREATE_CONTACT] Erro na validação do telefone: {e}")
            raise HTTPException(status_code=400, detail=f"Telefone inválido: {str(e)}")

        # Verificar se contato já existe
        logger.info(f"[CREATE_CONTACT] Verificando contato existente para telefone: {clean_phone}, company_id: {request_data.company_id}")
        existing_contact = db.query(Contact).filter(
            Contact.phone == clean_phone,
            Contact.company_id == request_data.company_id
        ).first()

        if existing_contact:
            logger.info(f"[CREATE_CONTACT] Contato já existe: {existing_contact.name}")
            raise HTTPException(status_code=400, detail=f"Contato já existe com este telefone: {existing_contact.name}")

        # Verificar se já existe como lead ou cliente (apenas para informar, mas não bloquear)
        # Verificar se já existe como lead ou cliente (apenas para informar, mas não bloquear)
        from ..models import Lead, Customer

        logger.info(f"[CREATE_CONTACT] Verificando lead existente para telefone: {clean_phone}")
        existing_lead = db.query(Lead).filter(
            Lead.company_id == request_data.company_id,
            Lead.phone == clean_phone
        ).first()

        logger.info(f"[CREATE_CONTACT] Verificando cliente existente para telefone: {clean_phone}")
        existing_customer = db.query(Customer).filter(
            Customer.company_id == request_data.company_id,
            Customer.telefone == clean_phone
        ).first()

        if existing_lead:
            logger.info(f"[CREATE_CONTACT] Lead existente encontrado: {existing_lead.name}")

        if existing_customer:
            logger.info(f"[CREATE_CONTACT] Cliente existente encontrado: {existing_customer.nome}")

        # Se existe cliente, não criar contato (cliente é mais específico)
        if existing_customer:
            logger.info(f"[CREATE_CONTACT] Bloqueando criação - cliente já existe: {existing_customer.nome}")
            raise HTTPException(status_code=400, detail=f"Já existe um cliente com este telefone: {existing_customer.nome}")

        # Se existe lead mas não contato, vamos criar o contato e informar sobre o lead
        will_link_to_lead = existing_lead is not None
        logger.info(f"[CREATE_CONTACT] Will link to lead: {will_link_to_lead}")

        # Determinar client_id baseado no usuário
        if isinstance(user, Client):
            client_id = user.id
        else:
            # Se for User, buscar o client_id da empresa
            company_data = db.execute(text("""
                SELECT client_id FROM companies WHERE id = :company_id
            """), {"company_id": request_data.company_id}).fetchone()

            if not company_data:
                raise HTTPException(status_code=400, detail="Empresa não encontrada")

            client_id = company_data.client_id

        # Criar contato
        new_contact = Contact(
            client_id=client_id,
            company_id=request_data.company_id,
            phone=clean_phone,
            name=request_data.name.strip()
        )

        db.add(new_contact)
        db.commit()
        db.refresh(new_contact)

        logger.info(f"[CREATE_CONTACT] ✅ Contato criado - ID: {new_contact.id}, Nome: {new_contact.name}, Telefone: {new_contact.phone}")

        # Preparar mensagem de resposta
        if will_link_to_lead:
            message = f"Contato criado com sucesso e vinculado ao lead existente: {existing_lead.name}"
            logger.info(f"[CREATE_CONTACT] Contato vinculado ao lead ID: {existing_lead.id}")
        else:
            message = "Contato criado com sucesso"

        return {
            "success": True,
            "message": message,
            "contact": {
                "id": new_contact.id,
                "name": new_contact.name,
                "phone": new_contact.phone,
                "company_id": new_contact.company_id
            },
            "linked_to_lead": will_link_to_lead,
            "lead_info": {
                "id": existing_lead.id,
                "name": existing_lead.name
            } if existing_lead else None
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[CREATE_CONTACT] ❌ Erro na criação: {e}", exc_info=True)
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Erro ao criar contato: {str(e)}")
