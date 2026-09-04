"""create delivery attempts table"""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "attempts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("delivery_id", sa.Uuid(), nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("http_status", sa.Integer()),
        sa.Column("error_kind", sa.String(32)),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["delivery_id"], ["deliveries.id"]),
    )
    op.create_index("ix_attempts_delivery_id", "attempts", ["delivery_id"])


def downgrade() -> None:
    op.drop_index("ix_attempts_delivery_id", table_name="attempts")
    op.drop_table("attempts")
