"""AI layer: cost accounting, evidence fields, and cost caps (AI SOC Analyst milestone).

One migration for the whole AI groundwork, four concerns:

1. `agent_runs` gains `input_hash` (sha-256 of the canonical prompt
   input, for audit/repro) and `cost_usd` (real dollar cost from the
   provider's token counts) -- the run ledger the cost caps read.
2. `ai_analyses` gains `source` ("ai" | "rules" -- every analysis is
   marked so fallbacks are auditable), `evidence_ids` (the event ids
   the model cited, validated against what it was shown) and
   `false_positive_likelihood` (0..1).
3. `organization_settings` gains `ai_daily_cost_cap_usd` /
   `ai_monthly_cost_cap_usd` (NULL = platform defaults from
   app/config.py -- a missing cap never means "spend freely").
4. `ai_enabled` default flips true -> false AND existing rows are set
   to false: AI analysis is opt-in per organization (cost safety).
   The downgrade restores the true default but NOT the flipped values
   -- reverting an explicit opt-out decision would silently re-enable
   spend, so operators re-enable per organization if they truly
   downgrade (same "data is not restored" stance as d5e6f7a8b9c0).

Revision ID: b0c1d2e3f4a5
Revises: e7f8a9b0c1d2
Create Date: 2026-10-02
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "b0c1d2e3f4a5"
down_revision = "e7f8a9b0c1d2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # agent_runs: cost accounting + input fingerprint.
    op.add_column("agent_runs", sa.Column("input_hash", sa.String(length=64), nullable=True))
    op.add_column("agent_runs", sa.Column("cost_usd", sa.Float(), nullable=True))

    # ai_analyses: marking, evidence grounding, false-positive estimate.
    op.add_column("ai_analyses", sa.Column("source", sa.String(length=20), nullable=True))
    op.add_column(
        "ai_analyses", sa.Column("evidence_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=True)
    )
    op.add_column(
        "ai_analyses", sa.Column("false_positive_likelihood", sa.Float(), nullable=True)
    )

    # organization_settings: per-org cost caps + opt-in default.
    op.add_column(
        "organization_settings", sa.Column("ai_daily_cost_cap_usd", sa.Float(), nullable=True)
    )
    op.add_column(
        "organization_settings", sa.Column("ai_monthly_cost_cap_usd", sa.Float(), nullable=True)
    )
    op.alter_column(
        "organization_settings",
        "ai_enabled",
        existing_type=sa.Boolean(),
        server_default=sa.text("false"),
        nullable=False,
    )
    # Backfill: every existing organization starts with AI off. The
    # feature did not exist until this change, so "off" loses nothing.
    op.execute("UPDATE organization_settings SET ai_enabled = false")


def downgrade() -> None:
    op.alter_column(
        "organization_settings",
        "ai_enabled",
        existing_type=sa.Boolean(),
        server_default=sa.text("true"),
        nullable=False,
    )
    op.drop_column("organization_settings", "ai_monthly_cost_cap_usd")
    op.drop_column("organization_settings", "ai_daily_cost_cap_usd")
    op.drop_column("ai_analyses", "false_positive_likelihood")
    op.drop_column("ai_analyses", "evidence_ids")
    op.drop_column("ai_analyses", "source")
    op.drop_column("agent_runs", "cost_usd")
    op.drop_column("agent_runs", "input_hash")
