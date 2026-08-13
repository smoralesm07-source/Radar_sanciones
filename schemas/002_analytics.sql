CREATE VIEW IF NOT EXISTS entity_sanction_profile AS
SELECT e.entity_id,e.rut,e.legal_name,
       COUNT(f.sanction_fact_id) AS events_total,
       COUNT(DISTINCT c.authority) AS authorities_total,
       MAX(c.decision_date) AS last_event_date,
       SUM(CASE WHEN f.laft_direct=1 THEN 1 ELSE 0 END) AS laft_events
FROM legal_entity e
LEFT JOIN sanction_fact f ON f.entity_id=e.entity_id
LEFT JOIN sanction_case c ON c.sanction_case_id=f.sanction_case_id
GROUP BY e.entity_id,e.rut,e.legal_name;
