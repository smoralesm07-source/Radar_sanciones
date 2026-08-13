from radar_sanciones.interop import adapt_entity, global_entity_id, normalize_rut


def test_valid_rut_gets_canonical_global_id():
    assert normalize_rut("96.921.130-0") == "96921130-0"
    assert global_entity_id("96.921.130-0") == "ENT-RUT-96921130-0"


def test_legacy_core_id_is_preserved_as_source_id():
    row = adapt_entity({"entity_id":"ENT-RUT-969211300","rut":"96.921.130-0","nombre_uaf":"Ejemplo S.A."})
    assert row["entity_id"] == "ENT-RUT-96921130-0"
    assert row["source_entity_id"] == "ENT-RUT-969211300"


def test_invalid_or_missing_rut_never_promotes_name_identity():
    row = adapt_entity({"entity_id":"ENT-NAME-ABC","rut":"","nombre_uaf":"Solo Nombre"})
    assert row["entity_id"] is None
    assert row["candidate_entity_id"] == "ENT-NAME-ABC"
    assert row["identity_status"] == "UNRESOLVED"
