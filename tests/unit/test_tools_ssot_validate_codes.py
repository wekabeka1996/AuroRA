from tools.ssot_validate import _check_unknown_top_level, check_missing_required_keys, check_unknown_and_nulls


def test_ssot_validate_exit_codes(tmp_path):
    # Test missing required key -> exit 50
    cfg_missing = {"name": "test"}
    try:
        check_missing_required_keys(cfg_missing)
        assert False, "Should have exited with 50"
    except SystemExit as e:
        assert e.code == 50

    # Test unknown top-level -> exit 20
    schema = {"properties": {"name": {}}}
    cfg_unknown = {"name": "test", "unknown_key": 1}
    try:
        _check_unknown_top_level(cfg_unknown, schema)
        assert False, "Should have exited with 20"
    except SystemExit as e:
        assert e.code == 20

    # Test null/empty critical section -> exit 30
    cfg_null = {"risk": None}
    try:
        check_unknown_and_nulls(cfg_null, schema)
        assert False, "Should have exited with 30"
    except SystemExit as e:
        assert e.code == 30
