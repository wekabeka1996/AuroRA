import types
import sys
from pathlib import Path

import pytest


def _fake_ccxt_module():
    mod = types.SimpleNamespace()

    class FakeExchange:
        def __init__(self, cfg):
            self.cfg = cfg

        def set_sandbox_mode(self, on):
            self.sandbox = on

        def fetch_balance(self, params=None):
            return {
                "USDT": {"free": 100.0, "used": 0.0, "total": 100.0},
                "info": {"positions": []},
            }

    # expose by common binance id used in env
    setattr(mod, 'binanceusdm', FakeExchange)
    return mod


def test_wallet_check_succeeds_without_keys_in_dry_run(monkeypatch, tmp_path: Path):
    # Ensure repo-relative artifacts path exists
    (Path('artifacts')).mkdir(exist_ok=True)
    # Inject fake ccxt
    sys.modules['ccxt'] = _fake_ccxt_module()
    # Import CLI and call function directly
    from tools.auroractl import wallet_check
    # Call and catch typer.Exit
    import typer
    with pytest.raises(typer.Exit) as ei:
        wallet_check()
    # Exit 0 on success
    assert getattr(ei.value, 'exit_code', None) == 0
    assert (Path('artifacts') / 'wallet_check.json').exists()


def test_wallet_check_withdrawals_disabled_exits_nonzero(monkeypatch, tmp_path: Path):
    # Arrange artifacts dir
    (Path('artifacts')).mkdir(exist_ok=True)

    # Fake env: live (not testnet), not dry-run, keys present
    from types import SimpleNamespace
    fake_env = SimpleNamespace(
        AURORA_MODE="prod",
        EXCHANGE_TESTNET=False,
        DRY_RUN=False,
        BINANCE_API_KEY="k",
        BINANCE_API_SECRET="s",
        EXCHANGE_ID="binanceusdm",
        EXCHANGE_USE_FUTURES=True,
        BINANCE_RECV_WINDOW=5000,
    )

    # Fake ccxt with currencies showing withdrawals disabled
    class _FX:
        def __init__(self, cfg):
            self.cfg = cfg
        def set_sandbox_mode(self, on):
            pass
        def fetch_balance(self, params=None):
            return {"USDT": {"free": 10.0, "used": 0.0, "total": 10.0}, "info": {"positions": []}}
        def load_markets(self):
            return {}
        def fetch_currencies(self):
            return {
                'USDT': {
                    'info': {
                        'networkList': [
                            {'network': 'TRX', 'withdrawEnable': False, 'withdrawMin': '5', 'withdrawFee': '1'}
                        ]
                    }
                }
            }
    import types as _types
    fake_ccxt = _types.ModuleType('ccxt')
    setattr(fake_ccxt, 'binanceusdm', _FX)
    sys.modules['ccxt'] = fake_ccxt

    # Patch env loader within module
    import tools.auroractl as aur
    monkeypatch.setattr(aur, 'load_env', lambda dotenv=False: fake_env)

    # Act
    import typer
    with pytest.raises(typer.Exit) as ei:
        aur.wallet_check()
    # withdrawals disabled ⇒ exit code 4
    assert getattr(ei.value, 'exit_code', None) == 4
    assert (Path('artifacts') / 'wallet_check.json').exists()
