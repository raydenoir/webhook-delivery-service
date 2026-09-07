"""добавляем счетчик попыток и время отправки"""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "deliveries",
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "deliveries",
        sa.Column(
            "next_attempt_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
        ),
    )
    op.execute("UPDATE deliveries SET next_attempt_at = NULL WHERE status != 'queued'")
    # учитываем попытку текущего цикла, начатую до добавления счетчика
    op.execute(
        "UPDATE deliveries SET attempt_count = 1 "
        "WHERE status != 'queued' AND EXISTS "
        "(SELECT 1 FROM attempts WHERE attempts.delivery_id = deliveries.id)"
    )


def downgrade() -> None:
    op.drop_column("deliveries", "next_attempt_at")
    op.drop_column("deliveries", "attempt_count")
