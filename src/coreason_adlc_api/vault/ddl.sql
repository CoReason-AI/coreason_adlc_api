
-- 6.5 Secure Vault (FR-API-013)
CREATE SCHEMA IF NOT EXISTS vault;

CREATE TABLE IF NOT EXISTS vault.secrets (
    secret_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    auc_id VARCHAR(50) NOT NULL,
    service_name VARCHAR(50) NOT NULL, -- e.g., 'openai', 'deepseek'

    -- Security
    encrypted_value TEXT NOT NULL, -- Must be AES-256 Encrypted
    encryption_key_id VARCHAR(50), -- Reference to key version (optional rotation support)

    created_by UUID REFERENCES identity.users(user_uuid),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    UNIQUE(auc_id, service_name) -- Prevent duplicate keys for same service/project
);
