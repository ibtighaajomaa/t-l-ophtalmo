-- =============================================================================
-- Init script : Base de données d'audit FTHNet
-- Objectif : Tracer qui a envoyé quelle image, quand, avec quel résultat
-- Conformité : RGPD / Données de santé (logs immuables, pseudonymisés)
-- =============================================================================

-- Activer l'extension pour chiffrement (si disponible)
-- CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- Table principale d'audit
CREATE TABLE IF NOT EXISTS audit_predictions (
    id              SERIAL PRIMARY KEY,
    timestamp       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    user_id         VARCHAR(255) NOT NULL,
    user_role       VARCHAR(100),
    pseudo_patient_id VARCHAR(255),
    image_hash      VARCHAR(64),
    image_size_kb   INTEGER,
    quality_score   NUMERIC(5,2),
    quality_category VARCHAR(20),
    inference_time_ms INTEGER,
    client_ip       INET,
    user_agent      VARCHAR(500),
    session_id      VARCHAR(255),
    api_endpoint    VARCHAR(255) NOT NULL DEFAULT '/predict',
    status_code     INTEGER DEFAULT 200,
    error_message   TEXT,
    dicom_anonymized BOOLEAN DEFAULT TRUE,
    retention_until DATE NOT NULL DEFAULT (NOW() + INTERVAL '10 years'),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE audit_predictions IS 'Audit trail des inférences FTHNet';

CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_predictions(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_audit_user ON audit_predictions(user_id);
CREATE INDEX IF NOT EXISTS idx_audit_pseudo_patient ON audit_predictions(pseudo_patient_id);
CREATE INDEX IF NOT EXISTS idx_audit_category ON audit_predictions(quality_category);
CREATE INDEX IF NOT EXISTS idx_audit_retention ON audit_predictions(retention_until);
CREATE INDEX IF NOT EXISTS idx_audit_errors ON audit_predictions(status_code) WHERE status_code != 200;

CREATE TABLE IF NOT EXISTS security_events (
    id              SERIAL PRIMARY KEY,
    timestamp       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    event_type      VARCHAR(50) NOT NULL,
    client_ip       INET NOT NULL,
    user_agent      VARCHAR(500),
    attempted_user  VARCHAR(255),
    details         JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_sec_events_timestamp ON security_events(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_sec_events_ip ON security_events(client_ip);
CREATE INDEX IF NOT EXISTS idx_sec_events_type ON security_events(event_type);

CREATE OR REPLACE VIEW v_audit_daily_stats AS
SELECT 
    DATE(timestamp) as day,
    COUNT(*) as total_predictions,
    COUNT(DISTINCT user_id) as unique_users,
    COUNT(DISTINCT pseudo_patient_id) as unique_patients,
    ROUND(AVG(quality_score), 2) as avg_score,
    COUNT(*) FILTER (WHERE quality_category = 'Good') as good_count,
    COUNT(*) FILTER (WHERE quality_category = 'Usable') as usable_count,
    COUNT(*) FILTER (WHERE quality_category = 'Reject') as reject_count,
    ROUND(AVG(inference_time_ms), 2) as avg_inference_ms
FROM audit_predictions
GROUP BY DATE(timestamp)
ORDER BY day DESC;

CREATE OR REPLACE VIEW v_security_events_recent AS
SELECT *
FROM security_events
WHERE timestamp > NOW() - INTERVAL '7 days'
ORDER BY timestamp DESC;

CREATE OR REPLACE FUNCTION purge_expired_audit_data()
RETURNS INTEGER AS $$
DECLARE
    deleted_count INTEGER;
BEGIN
    DELETE FROM audit_predictions 
    WHERE retention_until < NOW();
    GET DIAGNOSTICS deleted_count = ROW_COUNT;
    RETURN deleted_count;
END;
$$ LANGUAGE plpgsql;
