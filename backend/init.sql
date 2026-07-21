DROP TABLE IF EXISTS tools_audit;
CREATE TABLE tools_audit (
    id BIGSERIAL PRIMARY KEY,

    trace_id UUID NOT NULL,

    node VARCHAR(100) NOT NULL,
    tool VARCHAR(100) NOT NULL,

    start_time TIMESTAMPTZ NOT NULL,
    end_time TIMESTAMPTZ NOT NULL,

    args JSONB,
    result JSONB,

    status VARCHAR(20) NOT NULL,

    attempt INTEGER NOT NULL DEFAULT 0,

    error TEXT,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);