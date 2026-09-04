"""store accepted manual replay keys"""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "delivery_replays",
        sa.Column("delivery_id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("delivery_id", "idempotency_key"),
        sa.ForeignKeyConstraint(["delivery_id"], ["deliveries.id"]),
    )


def downgrade() -> None:
    op.drop_table("delivery_replays")
