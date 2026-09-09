"""добавляем секрет для подписи webhook"""

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "subscriptions", sa.Column("signing_secret", sa.String(200), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("subscriptions", "signing_secret")
