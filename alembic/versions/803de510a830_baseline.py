"""baseline

Revision ID: 803de510a830
Revises:
Create Date: 2025-12-30 06:16:48.719720

"""

from typing import Sequence, Union

from alembic import op  # type: ignore


# revision identifiers, used by Alembic.
revision: str = "803de510a830"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 1. Auth Schema (src/coreason_adlc_api/auth/ddl.sql)
    op.execute("CREATE SCHEMA IF NOT EXISTS identity;")

    op.execute("""
        CREATE TABLE IF NOT EXISTS identity.users (
            user_uuid UUID PRIMARY KEY,
            email VARCHAR(255) NOT NULL UNIQUE,
            full_name VARCHAR(255),
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            last_login TIMESTAMP WITH TIME ZONE
        );
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS identity.group_mappings (
            mapping_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            sso_group_oid UUID NOT NULL UNIQUE,
            role_name VARCHAR(50) NOT NULL,
            allowed_auc_ids TEXT[],
            description VARCHAR(255)
        );
    """)

    # 2. Vault Schema (src/coreason_adlc_api/vault/ddl.sql)
    op.execute("CREATE SCHEMA IF NOT EXISTS vault;")

    op.execute("""
        CREATE TABLE IF NOT EXISTS vault.secrets (
            secret_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            auc_id VARCHAR(50) NOT NULL,
            service_name VARCHAR(50) NOT NULL,
            encrypted_value TEXT NOT NULL,
            encryption_key_id VARCHAR(50),
            created_by UUID REFERENCES identity.users(user_uuid),
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            UNIQUE(auc_id, service_name)
        );
    """)

    # 3. Workbench Schema (src/coreason_adlc_api/workbench/ddl.sql)
    op.execute("CREATE SCHEMA IF NOT EXISTS workbench;")

    op.execute("""
        CREATE TABLE IF NOT EXISTS workbench.agent_drafts (
            draft_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_uuid UUID REFERENCES identity.users(user_uuid),
            auc_id VARCHAR(50) NOT NULL,
            title VARCHAR(255) NOT NULL,
            oas_content JSONB NOT NULL,
            runtime_env VARCHAR(64),
            status VARCHAR(20) DEFAULT 'DRAFT' NOT NULL CHECK (status IN ('DRAFT', 'PENDING', 'APPROVED', 'REJECTED')),
            agent_tools_index TSVECTOR,
            locked_by_user UUID REFERENCES identity.users(user_uuid),
            lock_expiry TIMESTAMP WITH TIME ZONE,
            is_deleted BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        );
    """)

    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_drafts_gin ON workbench.agent_drafts USING GIN (agent_tools_index);"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_drafts_auc ON workbench.agent_drafts(auc_id);"
    )

    # 4. Telemetry Schema (src/coreason_adlc_api/telemetry/ddl.sql)
    op.execute("CREATE SCHEMA IF NOT EXISTS telemetry;")

    op.execute("""
        CREATE TABLE IF NOT EXISTS telemetry.telemetry_logs (
            log_id UUID DEFAULT gen_random_uuid(),
            timestamp TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
            user_uuid UUID,
            auc_id VARCHAR(50),
            model_name VARCHAR(100),
            request_payload JSONB,
            response_payload JSONB,
            cost_usd DECIMAL(10, 6),
            latency_ms INTEGER
        ) PARTITION BY RANGE (timestamp);
    """)

    op.execute(
        "ALTER TABLE telemetry.telemetry_logs ALTER COLUMN request_payload SET STORAGE EXTENDED;"
    )
    op.execute(
        "ALTER TABLE telemetry.telemetry_logs ALTER COLUMN response_payload SET STORAGE EXTENDED;"
    )

    op.execute("""
        CREATE TABLE IF NOT EXISTS telemetry.telemetry_logs_default PARTITION OF telemetry.telemetry_logs
        DEFAULT;
    """)


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP TABLE IF EXISTS telemetry.telemetry_logs_default;")
    op.execute("DROP TABLE IF EXISTS telemetry.telemetry_logs;")
    op.execute("DROP SCHEMA IF EXISTS telemetry;")

    op.execute("DROP TABLE IF EXISTS workbench.agent_drafts;")
    op.execute("DROP SCHEMA IF EXISTS workbench;")

    op.execute("DROP TABLE IF EXISTS vault.secrets;")
    op.execute("DROP SCHEMA IF EXISTS vault;")

    op.execute("DROP TABLE IF EXISTS identity.group_mappings;")
    op.execute("DROP TABLE IF EXISTS identity.users;")
    op.execute("DROP SCHEMA IF EXISTS identity;")
