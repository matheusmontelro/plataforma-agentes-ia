from backend.models import Client
from backend.routes.account_profile_routes import AccountBillingProfilePayload, update_account_profile


class FakeDB:
    def __init__(self):
        self.commits = 0
        self.refreshed = []

    def commit(self):
        self.commits += 1

    def refresh(self, obj):
        self.refreshed.append(obj)


def test_update_account_profile_does_not_change_master_email():
    client = Client(
        id=7,
        email="master@example.com",
        company_id=3,
        billing_profile={
            "full_name": "Master Original",
            "email": "master@example.com",
            "cellphone": "11988887777",
            "document": "12345678909",
        },
    )
    db = FakeDB()

    response = update_account_profile(
        AccountBillingProfilePayload(
            full_name="Master Atualizado",
            email="other@example.com",
            cellphone="11988887777",
            document="12345678909",
        ),
        db=db,
        current_user=client,
    )

    assert response.email == "master@example.com"
    assert response.billing_profile["email"] == "master@example.com"
    assert response.billing_profile["full_name"] == "Master Atualizado"
    assert response.profile_complete is True
    assert client.billing_profile["email"] == "master@example.com"
    assert db.commits == 1
    assert db.refreshed == [client]
