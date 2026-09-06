"""добавляем срок захвата доставки"""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("deliveries", sa.Column("lease_token", sa.Uuid(), nullable=True))
    op.add_column(
        "deliveries",
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("deliveries", "lease_until")
    op.drop_column("deliveries", "lease_token")
