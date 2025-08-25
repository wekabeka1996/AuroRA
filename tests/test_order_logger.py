from pathlib import Path
from core.order_logger import OrderLoggers


def test_order_loggers_create_and_write(tmp_path: Path):
    ol = OrderLoggers(
        success_path=tmp_path/"succ.jsonl",
        failed_path=tmp_path/"fail.jsonl",
        denied_path=tmp_path/"deny.jsonl",
        max_mb=1,
        backups=1,
    )
    ol.log_success(ts=1, symbol="BTC/USDT", side="buy", qty=1, price=100)
    ol.log_failed(ts=1, symbol="BTC/USDT", side="buy", qty=1, price=100, error_code="E", error_msg="m")
    ol.log_denied(ts=1, symbol="BTC/USDT", side="buy", qty=1, price=100, deny_reason="trap")
    assert (tmp_path/"succ.jsonl").exists()
    assert (tmp_path/"fail.jsonl").exists()
    assert (tmp_path/"deny.jsonl").exists()
