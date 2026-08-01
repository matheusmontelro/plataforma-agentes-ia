import os

os.environ.setdefault("DATABASE_URL", "sqlite:////tmp/agentive-flow-tag-nodes-test.db")

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.models import Base, Contact, ContactTag, FollowUpSequence, Lead, LeadCustomField, LeadCustomValue, Tag
from backend.services.flow_node_handlers import AddTagHandler, TagFilterHandler


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[
            Contact.__table__,
            Tag.__table__,
            ContactTag.__table__,
            FollowUpSequence.__table__,
            Lead.__table__,
            LeadCustomField.__table__,
            LeadCustomValue.__table__,
        ],
    )
    Session = sessionmaker(bind=engine)
    db = Session()
    try:
        yield db
    finally:
        db.close()


def seed_contact_and_tags(db):
    contact = Contact(
        id=1,
        client_id=1,
        company_id=7,
        phone="5500000000007",
        name="Ana",
    )
    vip_tag = Tag(id=10, company_id=7, name="VIP", color="#020323")
    lead_tag = Tag(id=11, company_id=7, name="Lead", color="#10B981")
    other_company_tag = Tag(id=12, company_id=8, name="Other", color="#EF4444")
    db.add_all([contact, vip_tag, lead_tag, other_company_tag])
    db.commit()
    return contact, vip_tag, lead_tag, other_company_tag


def test_add_tag_handler_adds_existing_company_tag_without_duplicates(db_session):
    contact, vip_tag, _, _ = seed_contact_and_tags(db_session)
    variables = {"phone": "00000000007"}

    result = AddTagHandler().execute(
        db=db_session,
        node_data={"tagId": vip_tag.id},
        variables=variables,
        company_id=7,
        flow_id=1,
    )

    assert result["success"] is True
    assert result["action"] == "added"
    assert result["contact_id"] == contact.id
    assert variables["add_tag"]["tag_name"] == "VIP"

    repeated = AddTagHandler().execute(
        db=db_session,
        node_data={"tagId": vip_tag.id},
        variables=variables,
        company_id=7,
        flow_id=1,
    )

    assert repeated["success"] is True
    assert repeated["action"] == "already_exists"
    assert db_session.query(ContactTag).filter(
        ContactTag.contact_id == contact.id,
        ContactTag.tag_id == vip_tag.id,
    ).count() == 1


def test_add_tag_handler_creates_contact_from_webhook_payload_when_missing(db_session, monkeypatch):
    _, _, lead_tag, _ = seed_contact_and_tags(db_session)
    handler = AddTagHandler()
    monkeypatch.setattr(handler, "_resolve_client_id", lambda db, company_id: 1)
    variables = {
        "trigger": {
            "name": "Cliente Exemplo",
            "whatsapp": "(00) 00000-0004",
            "body": {
                "name": "Cliente Exemplo",
                "whatsapp": "(00) 00000-0004",
            },
        },
        "whatsapp": "(00) 00000-0004",
        "name": "Cliente Exemplo",
    }

    result = handler.execute(
        db=db_session,
        node_data={"tagId": lead_tag.id},
        variables=variables,
        company_id=7,
        flow_id=1,
    )

    contact = db_session.query(Contact).filter(
        Contact.company_id == 7,
        Contact.phone == "5500000000004",
    ).one()
    assert result["success"] is True
    assert result["action"] == "added"
    assert result["contact_id"] == contact.id
    assert variables["contact_id"] == contact.id
    assert db_session.query(ContactTag).filter(
        ContactTag.contact_id == contact.id,
        ContactTag.tag_id == lead_tag.id,
    ).count() == 1


def test_add_tag_handler_skips_without_contact_phone_but_keeps_branch_running(db_session):
    _, _, lead_tag, _ = seed_contact_and_tags(db_session)
    variables = {"trigger": {"name": "Sem telefone"}}

    result = AddTagHandler().execute(
        db=db_session,
        node_data={"tagId": lead_tag.id},
        variables=variables,
        company_id=7,
        flow_id=1,
    )

    assert result["success"] is False
    assert result["action"] == "skipped"
    assert result["stop_branch"] is False


def test_tag_filter_handler_stops_branch_when_contact_lacks_tag(db_session):
    contact, vip_tag, lead_tag, _ = seed_contact_and_tags(db_session)
    db_session.add(ContactTag(contact_id=contact.id, tag_id=vip_tag.id))
    db_session.commit()

    variables = {"phone": "5500000000007"}

    matched = TagFilterHandler().execute(
        db=db_session,
        node_data={"tagId": vip_tag.id},
        variables=variables,
        company_id=7,
        flow_id=1,
    )

    assert matched["success"] is True
    assert matched["matched"] is True
    assert matched["stop_branch"] is False
    assert variables["tag_filter"]["tag_name"] == "VIP"

    blocked = TagFilterHandler().execute(
        db=db_session,
        node_data={"tagId": lead_tag.id},
        variables=variables,
        company_id=7,
        flow_id=1,
    )

    assert blocked["success"] is True
    assert blocked["matched"] is False
    assert blocked["stop_branch"] is True


def test_tag_filter_handler_supports_negative_tag_conditions(db_session):
    contact, vip_tag, lead_tag, _ = seed_contact_and_tags(db_session)
    db_session.add(ContactTag(contact_id=contact.id, tag_id=vip_tag.id))
    db_session.commit()

    variables = {"phone": "5500000000007"}

    allowed = TagFilterHandler().execute(
        db=db_session,
        node_data={
            "conditions": [
                {"source": "tag", "operator": "not_has_tag", "tagId": lead_tag.id},
            ],
            "actionOnMatch": "advance",
        },
        variables=variables,
        company_id=7,
        flow_id=1,
    )

    assert allowed["success"] is True
    assert allowed["matched"] is True
    assert allowed["stop_branch"] is False

    blocked = TagFilterHandler().execute(
        db=db_session,
        node_data={
            "conditions": [
                {"source": "tag", "operator": "not_has_tag", "tagId": vip_tag.id},
            ],
            "actionOnMatch": "advance",
        },
        variables=variables,
        company_id=7,
        flow_id=1,
    )

    assert blocked["success"] is True
    assert blocked["matched"] is False
    assert blocked["stop_branch"] is True


def test_tag_filter_handler_can_block_when_condition_matches(db_session):
    contact, vip_tag, _, _ = seed_contact_and_tags(db_session)
    db_session.add(ContactTag(contact_id=contact.id, tag_id=vip_tag.id))
    db_session.commit()

    result = TagFilterHandler().execute(
        db=db_session,
        node_data={
            "conditions": [
                {"source": "tag", "operator": "has_tag", "tagId": vip_tag.id},
            ],
            "actionOnMatch": "stop",
        },
        variables={"phone": "5500000000007"},
        company_id=7,
        flow_id=1,
    )

    assert result["success"] is True
    assert result["matched"] is True
    assert result["stop_branch"] is True


def test_tag_filter_handler_supports_custom_field_conditions(db_session):
    seed_contact_and_tags(db_session)
    lead = Lead(
        id=20,
        client_id=1,
        company_id=7,
        phone="5500000000007",
        name="Ana",
    )
    budget_field = LeadCustomField(
        id=30,
        company_id=7,
        field_name="Orçamento",
        field_key="orcamento",
        field_type="number",
        is_active=True,
    )
    status_field = LeadCustomField(
        id=31,
        company_id=7,
        field_name="Status",
        field_key="status",
        field_type="text",
        is_active=True,
    )
    db_session.add_all([
        lead,
        budget_field,
        status_field,
        LeadCustomValue(lead_id=20, custom_field_id=30, value="750"),
        LeadCustomValue(lead_id=20, custom_field_id=31, value="Qualificado"),
    ])
    db_session.commit()

    result = TagFilterHandler().execute(
        db=db_session,
        node_data={
            "conditionMatch": "all",
            "actionOnMatch": "advance",
            "conditions": [
                {
                    "source": "custom_field",
                    "operator": "greater_or_equal",
                    "customFieldId": budget_field.id,
                    "value": "500",
                },
                {
                    "source": "custom_field",
                    "operator": "contains",
                    "customFieldId": status_field.id,
                    "value": "qualif",
                },
            ],
        },
        variables={"phone": "5500000000007"},
        company_id=7,
        flow_id=1,
    )

    assert result["success"] is True
    assert result["matched"] is True
    assert result["stop_branch"] is False
    condition_results = result["conditions"]
    assert condition_results
    assert condition_results[0]["field_key"] == "orcamento"


def test_tag_filter_handler_supports_any_condition_mode(db_session):
    _, vip_tag, lead_tag, _ = seed_contact_and_tags(db_session)
    db_session.commit()

    result = TagFilterHandler().execute(
        db=db_session,
        node_data={
            "conditionMatch": "any",
            "conditions": [
                {"source": "tag", "operator": "has_tag", "tagId": vip_tag.id},
                {"source": "tag", "operator": "not_has_tag", "tagId": lead_tag.id},
            ],
        },
        variables={"phone": "5500000000007"},
        company_id=7,
        flow_id=1,
    )

    assert result["success"] is True
    assert result["matched"] is True
    assert result["stop_branch"] is False


def test_tag_nodes_reject_tags_from_other_companies(db_session):
    _, _, _, other_company_tag = seed_contact_and_tags(db_session)
    variables = {"phone": "5500000000007"}

    add_result = AddTagHandler().execute(
        db=db_session,
        node_data={"tagId": other_company_tag.id},
        variables=variables,
        company_id=7,
        flow_id=1,
    )
    filter_result = TagFilterHandler().execute(
        db=db_session,
        node_data={"tagId": other_company_tag.id},
        variables=variables,
        company_id=7,
        flow_id=1,
    )

    assert add_result["success"] is False
    assert add_result["stop_branch"] is True
    assert filter_result["success"] is False
    assert filter_result["stop_branch"] is True
