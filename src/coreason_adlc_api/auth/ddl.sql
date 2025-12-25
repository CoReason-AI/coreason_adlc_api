
-- 6.1 Schema Setup
CREATE SCHEMA IF NOT EXISTS identity;

-- 6.2 Identity & Access Management (FR-API-010)
CREATE TABLE IF NOT EXISTS identity.users (
    user_uuid UUID PRIMARY KEY,
    email VARCHAR(255) NOT NULL UNIQUE,
    full_name VARCHAR(255),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    last_login TIMESTAMP WITH TIME ZONE
);

CREATE TABLE IF NOT EXISTS identity.group_mappings (
    mapping_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    sso_group_oid UUID NOT NULL UNIQUE, -- IdP Object ID
    role_name VARCHAR(50) NOT NULL, -- e.g., 'MANAGER', 'DEVELOPER'
    allowed_auc_ids TEXT[], -- Array of Project IDs
    description VARCHAR(255)
);
