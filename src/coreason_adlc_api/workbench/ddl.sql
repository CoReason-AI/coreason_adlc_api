
-- 6.3 Workbench & Locking (FR-API-003, FR-API-011)
CREATE SCHEMA IF NOT EXISTS workbench;

CREATE TABLE IF NOT EXISTS workbench.agent_drafts (
    draft_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_uuid UUID REFERENCES identity.users(user_uuid),
    auc_id VARCHAR(50) NOT NULL,
    title VARCHAR(255) NOT NULL,

    -- Content & Versioning
    oas_content JSONB NOT NULL, -- Stores the Agent definition
    runtime_env VARCHAR(64), -- Pip freeze hash for environment consistency

    -- Approval Workflow
    status VARCHAR(20) DEFAULT 'DRAFT' NOT NULL CHECK (status IN ('DRAFT', 'PENDING', 'APPROVED', 'REJECTED')),

    -- Search Optimization
    agent_tools_index TSVECTOR,

    -- Pessimistic Locking Fields
    locked_by_user UUID REFERENCES identity.users(user_uuid),
    lock_expiry TIMESTAMP WITH TIME ZONE,

    -- Lifecycle
    is_deleted BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Index for fast searching of agent tools
CREATE INDEX IF NOT EXISTS idx_drafts_gin ON workbench.agent_drafts USING GIN (agent_tools_index);
-- Index for filtering by Project
CREATE INDEX IF NOT EXISTS idx_drafts_auc ON workbench.agent_drafts(auc_id);
