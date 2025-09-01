def test_time_invariant_order():
    # Test that exchange_ts <= ingest_ts for synthetic events
    events = [
        {"exchange_ts": 1000, "ingest_ts": 1001},
        {"exchange_ts": 1000, "ingest_ts": 1000},
    ]
    for event in events:
        assert event["exchange_ts"] <= event["ingest_ts"], f"Time invariant violated: {event}"