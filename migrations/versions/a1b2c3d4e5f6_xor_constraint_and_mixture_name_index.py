"""XOR constraint on inventory_items + index on mixtures.name

Revision ID: a1b2c3d4e5f6
Revises: c68d4ebca546
Create Date: 2026-04-17

"""
from alembic import op
import sqlalchemy as sa


revision = "a1b2c3d4e5f6"
down_revision = "c68d4ebca546"
branch_labels = None
depends_on = None


def upgrade():
    # 1. Remove any rows that violate the XOR invariant so the CHECK can be
    # applied safely.  We delete only rows where BOTH FKs are NULL (pure
    # orphans).  Rows with both set are left alone and will fail the CHECK —
    # the migration will raise so the operator can investigate.
    op.execute(
        "DELETE FROM inventory_items "
        "WHERE reagent_id IS NULL AND mixture_id IS NULL"
    )

    with op.batch_alter_table("inventory_items", schema=None) as batch_op:
        batch_op.create_check_constraint(
            "ck_inventory_reagent_xor_mixture",
            "(reagent_id IS NOT NULL AND mixture_id IS NULL) OR "
            "(reagent_id IS NULL AND mixture_id IS NOT NULL)",
        )

    with op.batch_alter_table("mixtures", schema=None) as batch_op:
        batch_op.create_index(
            "ix_mixtures_name",
            ["name"],
            unique=False,
        )


def downgrade():
    with op.batch_alter_table("mixtures", schema=None) as batch_op:
        batch_op.drop_index("ix_mixtures_name")

    with op.batch_alter_table("inventory_items", schema=None) as batch_op:
        batch_op.drop_constraint("ck_inventory_reagent_xor_mixture", type_="check")
