# backend/services/pipeline_service.py

import logging

from sqlalchemy.orm import Session
from sqlalchemy import func
from fastapi import HTTPException, status
from typing import Optional, List
from datetime import datetime, timezone

from backend.models import (
    Pipeline, PipelineStage, Lead, LeadPipelineHistory, Company, User
)

logger = logging.getLogger(__name__)


class PipelineService:

    @staticmethod
    def create_minimal_pipeline_for_company(company_id: int, db: Session, user_id: Optional[int] = None) -> Pipeline:
        """Cria pipeline mínimo com etapas 'Ganhou' e 'Perdido' apenas.
        A coluna 'Novo Lead' é hardcoded no frontend e não precisa de etapa no banco."""

        # Verificar se já existe um pipeline para a empresa
        existing_pipeline = db.query(Pipeline).filter(
            Pipeline.company_id == company_id
        ).first()

        if existing_pipeline:
            return existing_pipeline

        pipeline = Pipeline(
            company_id=company_id,
            name="Pipeline de Vendas",
            description="Configure suas etapas conforme necessidade",
            created_by_user_id=user_id,
            is_active=True
        )

        db.add(pipeline)
        db.flush()

        # Garantir etapas padrão "Ganhou" e "Perdido"
        PipelineService.ensure_standard_stages_for_pipeline(pipeline.id, db)

        db.commit()
        return pipeline


    @staticmethod
    def ensure_standard_stages_for_pipeline(pipeline_id: int, db: Session) -> None:
        """Garante que pipeline tenha etapas padrão: 'Ganhou' e 'Perdido'"""

        # Verificar se já existem etapas convertidas/perdidas
        existing_converted = db.query(PipelineStage).filter(
            PipelineStage.pipeline_id == pipeline_id,
            PipelineStage.is_converted_stage == True
        ).first()

        existing_lost = db.query(PipelineStage).filter(
            PipelineStage.pipeline_id == pipeline_id,
            PipelineStage.is_lost_stage == True
        ).first()

        # Buscar última ordem para posicionar as novas etapas
        last_order = db.query(func.max(PipelineStage.order)).filter(
            PipelineStage.pipeline_id == pipeline_id
        ).scalar() or 0

        # Criar etapa "Ganhou" se não existir
        if not existing_converted:
            converted_stage = PipelineStage(
                pipeline_id=pipeline_id,
                name="Ganhou",
                description="Cliente converteu - venda concluída com sucesso",
                color="#10B981",
                order=last_order + 1,
                order_index=last_order + 1,
                is_converted_stage=True,
                is_lost_stage=False
            )
            db.add(converted_stage)

        # Criar etapa "Perdido" se não existir
        if not existing_lost:
            lost_stage = PipelineStage(
                pipeline_id=pipeline_id,
                name="Perdido",
                description="Cliente perdido - venda não concluída",
                color="#EF4444",
                order=last_order + 2,
                order_index=last_order + 2,
                is_converted_stage=False,
                is_lost_stage=True
            )
            db.add(lost_stage)

        db.commit()

    @staticmethod
    def get_initial_stage_for_pipeline(pipeline_id: int, db: Session) -> Optional[PipelineStage]:
        """Busca a etapa inicial real ou a primeira etapa operacional do pipeline."""

        first_stage = db.query(PipelineStage).filter(
            PipelineStage.pipeline_id == pipeline_id,
            PipelineStage.is_first_stage == True
        ).order_by(PipelineStage.order.asc(), PipelineStage.id.asc()).first()

        if first_stage:
            return first_stage

        fallback_stage = db.query(PipelineStage).filter(
            PipelineStage.pipeline_id == pipeline_id,
            PipelineStage.is_converted_stage == False,
            PipelineStage.is_lost_stage == False
        ).order_by(PipelineStage.order.asc(), PipelineStage.id.asc()).first()

        if fallback_stage:
            logger.warning(
                "[PipelineService] Pipeline %s sem is_first_stage=true; usando etapa inicial por ordem stage_id=%s",
                pipeline_id,
                fallback_stage.id,
            )
            return fallback_stage

        return db.query(PipelineStage).filter(
            PipelineStage.pipeline_id == pipeline_id
        ).order_by(PipelineStage.order.asc(), PipelineStage.id.asc()).first()

    @staticmethod
    def assign_lead_to_first_stage(lead: Lead, db: Session) -> bool:
        """Atribui lead à primeira etapa disponível do pipeline da empresa"""

        # Buscar primeiro pipeline ativo da empresa
        pipeline = db.query(Pipeline).filter(
            Pipeline.company_id == lead.company_id,
            Pipeline.is_active == True
        ).first()

        if not pipeline:
            # Criar pipeline mínimo se não existir
            pipeline = PipelineService.create_minimal_pipeline_for_company(
                lead.company_id, db, None  # System without user
            )

        # Buscar primeira etapa. Se o pipeline legado não tiver is_first_stage,
        # usar a primeira etapa operacional pela ordem do kanban.
        first_stage = PipelineService.get_initial_stage_for_pipeline(pipeline.id, db)

        if first_stage:
            lead.pipeline_id = pipeline.id
            lead.current_stage_id = first_stage.id
            lead.pipeline_entered_at = datetime.now(timezone.utc)
            lead.last_stage_move_at = datetime.now(timezone.utc)
            return True

        return False

    @staticmethod
    def move_lead_to_stage(
        lead_id: int,
        new_stage_id: int,
        user_id: int,
        notes: Optional[str] = None,
        db: Session = None
    ) -> LeadPipelineHistory:
        """Move lead para nova etapa com histórico completo"""

        lead = db.query(Lead).filter(Lead.id == lead_id).first()
        new_stage = db.query(PipelineStage).filter(PipelineStage.id == new_stage_id).first()

        if not lead:
            raise HTTPException(status_code=404, detail="Lead não encontrado")

        if not new_stage:
            raise HTTPException(status_code=404, detail="Etapa não encontrada")

        # Validar que a etapa pertence ao mesmo pipeline do lead
        if lead.pipeline_id and new_stage.pipeline_id != lead.pipeline_id:
            raise HTTPException(
                status_code=400,
                detail="Etapa pertence a um pipeline diferente do lead"
            )

        old_stage_id = lead.current_stage_id

        # Calcular tempo na etapa anterior
        time_in_previous = None
        if lead.last_stage_move_at and old_stage_id:
            time_in_previous = int((datetime.now(timezone.utc) - lead.last_stage_move_at).total_seconds())

        # Criar histórico
        history = LeadPipelineHistory(
            lead_id=lead_id,
            company_id=lead.company_id,
            from_stage_id=old_stage_id,
            to_stage_id=new_stage_id,
            moved_by_user_id=user_id,
            notes=notes,
            time_in_previous_stage=time_in_previous
        )

        # Atualizar lead
        lead.current_stage_id = new_stage_id
        lead.last_stage_move_at = datetime.now(timezone.utc)

        # Se o lead não tinha pipeline, atribuir ao pipeline da nova etapa
        if not lead.pipeline_id:
            lead.pipeline_id = new_stage.pipeline_id
            lead.pipeline_entered_at = datetime.now(timezone.utc)

        db.add(history)
        db.commit()
        db.refresh(history)

        try:
            from backend.services.flow_event_service import trigger_crm_stage_entered
            started_flows = trigger_crm_stage_entered(
                db,
                lead=lead,
                stage=new_stage,
                moved_at=history.moved_at,
            )
            if started_flows:
                logger.info(
                    "[FlowBuilder] %s fluxo(s) CRM iniciados para lead_id=%s stage_id=%s",
                    started_flows,
                    lead.id,
                    new_stage.id,
                )
        except Exception as flow_event_err:
            logger.error(
                "[FlowBuilder] Erro ao iniciar fluxos CRM para lead_id=%s stage_id=%s: %s",
                lead.id,
                new_stage.id,
                flow_event_err,
            )

        # --- Lógica de Follow-up Automático por Estágio ---
        if new_stage.follow_up_sequence_id:
            # Se o estágio tem uma sequência configurada, atualizamos o lead e iniciamos
            lead.follow_up_sequence_id = new_stage.follow_up_sequence_id
            db.commit()

            # Disparar task (importação local para evitar ciclo)
            from backend.worker.tasks import enviar_passo_followup
            from backend.models import FollowUpStep
            from datetime import timedelta

            # Buscar dados da empresa para disparar
            company = db.query(Company).filter(Company.id == lead.company_id).first()

            has_zapi = company and company.zapi_instance_id and company.zapi_token
            has_waha = company and company.waha_enabled and company.waha_session_name

            if has_zapi or has_waha:
                # Calcular delay do passo 1
                step1 = db.query(FollowUpStep).filter(
                    FollowUpStep.follow_up_sequence_id == new_stage.follow_up_sequence_id,
                    FollowUpStep.step_number == 1
                ).first()

                eta = None
                if step1 and step1.send_after > 0:
                    now_utc = datetime.now(timezone.utc)
                    if step1.send_after_unit == 'minutes':
                        eta = now_utc + timedelta(minutes=step1.send_after)
                    elif step1.send_after_unit == 'hours':
                        eta = now_utc + timedelta(hours=step1.send_after)
                    elif step1.send_after_unit == 'days':
                        eta = now_utc + timedelta(days=step1.send_after)

                # Iniciar passo 1 da nova sequência
                from backend.services.company_access_control import capture_company_job_epoch

                operational_epoch = capture_company_job_epoch(db, lead.company_id)

                # Se tiver ETA, usa apply_async, senão delay (imediato)
                if eta:
                    enviar_passo_followup.apply_async(
                        args=[
                            lead.id,
                            1,
                            new_stage.follow_up_sequence_id,
                            new_stage.follow_up_sequence_id,
                            operational_epoch,
                        ],
                        eta=eta
                    )
                else:
                    enviar_passo_followup.delay(
                        lead_id=lead.id,
                        step_number=1,
                        expected_sequence_id=new_stage.follow_up_sequence_id,
                        sequence_id=new_stage.follow_up_sequence_id,
                        operational_epoch=operational_epoch,
                    )
                db.commit()
        # --------------------------------------------------



        return history

    @staticmethod
    def get_pipeline_kanban_data(
        company_id: int,
        pipeline_id: Optional[int] = None,
        db: Session = None
    ) -> dict:
        """Retorna dados formatados para visualização Kanban do pipeline"""

        # Buscar pipeline (ou o primeiro ativo se não especificado)
        if pipeline_id:
            pipeline = db.query(Pipeline).filter(
                Pipeline.id == pipeline_id,
                Pipeline.company_id == company_id
            ).first()
        else:
            pipeline = db.query(Pipeline).filter(
                Pipeline.company_id == company_id,
                Pipeline.is_active == True
            ).first()

        if not pipeline:
            return {"pipeline": None, "stages": []}

        # Buscar todas as etapas do pipeline em ordem
        stages = db.query(PipelineStage).filter(
            PipelineStage.pipeline_id == pipeline.id
        ).order_by(PipelineStage.order).all()

        # Para cada etapa, buscar os leads correspondentes
        stages_data = []
        for stage in stages:
            leads = db.query(Lead).filter(
                Lead.current_stage_id == stage.id,
                Lead.company_id == company_id
            ).order_by(Lead.created_at.desc()).all()

            stages_data.append({
                "id": stage.id,
                "name": stage.name,
                "description": stage.description,
                "color": stage.color,
                "order": stage.order,
                "is_first_stage": stage.is_first_stage,
                "is_converted_stage": stage.is_converted_stage,
                "is_lost_stage": stage.is_lost_stage,
                "leads_count": len(leads),
                "leads": [
                    {
                        "id": lead.id,
                        "name": lead.name,
                        "phone": lead.phone,
                        "created_at": lead.created_at.isoformat() if lead.created_at else None,
                        "pipeline_entered_at": lead.pipeline_entered_at.isoformat() if lead.pipeline_entered_at else None,
                        "last_stage_move_at": lead.last_stage_move_at.isoformat() if lead.last_stage_move_at else None,
                        "source_id": lead.source_id,
                        "thumbnail_url": lead.thumbnail_url
                    }
                    for lead in leads
                ]
            })

        return {
            "pipeline": {
                "id": pipeline.id,
                "name": pipeline.name,
                "description": pipeline.description,
                "is_active": pipeline.is_active
            },
            "stages": stages_data
        }

    @staticmethod
    def create_custom_stage(
        pipeline_id: int,
        stage_data: dict,
        db: Session
    ) -> PipelineStage:
        """Adiciona nova etapa personalizada ao pipeline"""

        # Validar que pipeline existe
        pipeline = db.query(Pipeline).filter(Pipeline.id == pipeline_id).first()
        if not pipeline:
            raise HTTPException(status_code=404, detail="Pipeline não encontrado")

        # Determinar próxima ordem
        last_order = db.query(func.max(PipelineStage.order)).filter(
            PipelineStage.pipeline_id == pipeline_id
        ).scalar() or 0

        # Validar que não existe outra etapa converted/lost (se especificado)
        if stage_data.get("is_converted_stage", False):
            existing_converted = db.query(PipelineStage).filter(
                PipelineStage.pipeline_id == pipeline_id,
                PipelineStage.is_converted_stage == True
            ).first()
            if existing_converted:
                raise HTTPException(
                    status_code=400,
                    detail="Já existe uma etapa de 'Convertido' neste pipeline"
                )

        if stage_data.get("is_lost_stage", False):
            existing_lost = db.query(PipelineStage).filter(
                PipelineStage.pipeline_id == pipeline_id,
                PipelineStage.is_lost_stage == True
            ).first()
            if existing_lost:
                raise HTTPException(
                    status_code=400,
                    detail="Já existe uma etapa de 'Perdido' neste pipeline"
                )

        percentage_base_stage_id = stage_data.get("percentage_base_stage_id")
        if percentage_base_stage_id is not None:
            base_stage = db.query(PipelineStage).filter(
                PipelineStage.id == percentage_base_stage_id,
                PipelineStage.pipeline_id == pipeline_id
            ).first()
            if not base_stage:
                raise HTTPException(
                    status_code=400,
                    detail="Etapa base do percentual não pertence a este pipeline"
                )

        stage = PipelineStage(
            pipeline_id=pipeline_id,
            order=last_order + 1,
            order_index=last_order + 1,  # Manter sincronizado com order
            name=stage_data["name"],
            color=stage_data.get("color", "#3B82F6"),
            description=stage_data.get("description", ""),
            is_converted_stage=stage_data.get("is_converted_stage", False),
            is_lost_stage=stage_data.get("is_lost_stage", False),
            auto_advance_days=stage_data.get("auto_advance_days"),
            follow_up_sequence_id=stage_data.get("follow_up_sequence_id"),
            percentage_base_stage_id=percentage_base_stage_id
        )

        db.add(stage)
        db.commit()
        db.refresh(stage)

        return stage

    @staticmethod
    def update_stage_order(
        stage_orders: List[dict],  # [{"stage_id": 1, "order": 1}, ...]
        db: Session
    ) -> bool:
        """Atualiza ordem das etapas do pipeline"""

        try:
            for stage_order in stage_orders:
                stage_id = stage_order["stage_id"]
                new_order = stage_order["order"]

                stage = db.query(PipelineStage).filter(
                    PipelineStage.id == stage_id
                ).first()

                if stage:
                    stage.order = new_order

            db.commit()
            return True

        except Exception as e:
            db.rollback()
            raise HTTPException(
                status_code=500,
                detail=f"Erro ao atualizar ordem das etapas: {str(e)}"
            )

    @staticmethod
    def get_lead_pipeline_history(lead_id: int, db: Session) -> List[dict]:
        """Retorna histórico completo de movimentação do lead no pipeline"""

        history = db.query(LeadPipelineHistory).filter(
            LeadPipelineHistory.lead_id == lead_id
        ).order_by(LeadPipelineHistory.moved_at.desc()).all()

        result = []
        for h in history:
            result.append({
                "id": h.id,
                "from_stage": {
                    "id": h.from_stage.id,
                    "name": h.from_stage.name
                } if h.from_stage else None,
                "to_stage": {
                    "id": h.to_stage.id,
                    "name": h.to_stage.name
                } if h.to_stage else None,
                "moved_by": {
                    "id": h.moved_by.id,
                    "name": h.moved_by.name
                } if h.moved_by else None,
                "moved_at": h.moved_at.isoformat() if h.moved_at else None,
                "notes": h.notes,
                "time_in_previous_stage": h.time_in_previous_stage
            })

        return result

    @staticmethod
    def get_pipeline_statistics(
        company_id: int,
        pipeline_id: Optional[int] = None,
        db: Session = None
    ) -> dict:
        """Retorna estatísticas do pipeline para analytics"""

        query = db.query(Lead).filter(Lead.company_id == company_id)

        if pipeline_id:
            query = query.filter(Lead.pipeline_id == pipeline_id)

        leads = query.all()

        # Estatísticas gerais
        total_leads = len(leads)
        leads_with_pipeline = len([l for l in leads if l.pipeline_id])

        # Estatísticas por etapa
        stage_stats = {}
        for lead in leads:
            if lead.current_stage_id:
                stage_id = lead.current_stage_id
                if stage_id not in stage_stats:
                    stage_stats[stage_id] = {
                        "stage_id": stage_id,
                        "stage_name": lead.current_stage.name if lead.current_stage else "Desconhecida",
                        "lead_count": 0,
                        "avg_time_in_stage": 0,
                        "converted_count": 0,
                        "lost_count": 0
                    }

                stage_stats[stage_id]["lead_count"] += 1

                # Verificar se está em etapa convertida/perdida
                if lead.current_stage:
                    if lead.current_stage.is_converted_stage:
                        stage_stats[stage_id]["converted_count"] += 1
                    elif lead.current_stage.is_lost_stage:
                        stage_stats[stage_id]["lost_count"] += 1

        return {
            "total_leads": total_leads,
            "leads_with_pipeline": leads_with_pipeline,
            "pipeline_adoption_rate": (leads_with_pipeline / total_leads * 100) if total_leads > 0 else 0,
            "stage_statistics": list(stage_stats.values())
        }
