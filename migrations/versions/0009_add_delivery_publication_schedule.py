"""добавляем паузу публикации и индексы для фоновой обработки"""

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "deliveries",
        sa.Column(
            "publish_after",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_deliveries_ready", "deliveries", ["status", "next_attempt_at", "id"]
    )
    op.create_index(
        "ix_deliveries_expired", "deliveries", ["status", "lease_until", "id"]
    )


def downgrade() -> None:
    op.drop_index("ix_deliveries_expired", table_name="deliveries")
    op.drop_index("ix_deliveries_ready", table_name="deliveries")
    op.drop_column("deliveries", "publish_after")
