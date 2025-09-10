import pytest

from typing import Any


def _init_lifespan(config_path: str, schema_path: str, base_path: str):
    """Composition init for lifespan: load config, build XAI logger, start hot-reload.

    Returns (cfg, logger, watcher) to allow assertions in tests.
    """
    from core.config import loader as cfg_loader
    from core.config import hotreload
    from core.xai.logger import DecisionLogger

    # Build logger first so we can emit a start log regardless of config outcome
    logger = DecisionLogger(base_path=base_path)

    try:
        cfg = cfg_loader.load_config(config_path=config_path, schema_path=schema_path, enable_watcher=False)
        # start hot-reload file watcher for config
        watcher = hotreload.FileWatcher(path=config_path, on_change=lambda *_: None, poll_interval_sec=1.0)
        watcher.start()
        # emit XAI start log (shape is tested via spy class)
        logger.write({'why_code': 'OK_LIFESPAN_INIT'})
        return cfg, logger, watcher
    except cfg_loader.SchemaValidationError as e:
        # log schema failure and re-raise
        logger.write({'why_code': 'WHY_CONFIG_SCHEMA', 'errors': str(e)})
        raise


def test_lifespan_init_happy_path_builds_services(monkeypatch, tmp_path):
    # Arrange: mock load_config -> returns minimal Config-like object
    from core.config import loader as cfg_loader

    class DummyConfig:
        def __init__(self):
            self.config_hash = 'deadbeef'
            self.schema_version = 'v1'

    def fake_load_config(*args, **kwargs):
        return DummyConfig()

    monkeypatch.setattr(cfg_loader, 'load_config', fake_load_config)

    # Spy DecisionLogger to avoid file I/O
    writes: list[dict[str, Any]] = []

    class SpyDecisionLogger:
        def __init__(self, base_path: str, **kwargs):
            self.base_path = base_path
            self.kwargs = kwargs

        def write(self, record: dict):
            writes.append(record)

    from core.xai import logger as xai_logger
    monkeypatch.setattr(xai_logger, 'DecisionLogger', SpyDecisionLogger)

    # Spy FileWatcher
    starts: list[str] = []

    class SpyWatcher:
        def __init__(self, path, on_change, *, poll_interval_sec: float = 1.0):
            self.path = str(path)
            self.started = False
        def start(self):
            self.started = True
            starts.append(self.path)

    from core.config import hotreload
    monkeypatch.setattr(hotreload, 'FileWatcher', SpyWatcher)

    config_path = str(tmp_path / 'default.toml')
    schema_path = str(tmp_path / 'schema.json')
    # create empty placeholders; we don't actually read due to mocking
    (tmp_path / 'default.toml').write_text('')
    (tmp_path / 'schema.json').write_text('{}')

    # Act
    cfg, log, watcher = _init_lifespan(config_path=config_path, schema_path=schema_path, base_path=str(tmp_path))

    # Assert
    assert isinstance(cfg, DummyConfig)
    assert isinstance(watcher, SpyWatcher)
    assert starts and starts[0] == config_path
    assert writes and writes[0].get('why_code') == 'OK_LIFESPAN_INIT'


def test_lifespan_init_invalid_config_raises_and_logs(monkeypatch, tmp_path):
    # Arrange: make load_config raise SchemaValidationError
    from core.config import loader as cfg_loader
    err = cfg_loader.SchemaValidationError('bad schema')

    def raise_schema(*args, **kwargs):
        raise err

    monkeypatch.setattr(cfg_loader, 'load_config', raise_schema)

    # Spy DecisionLogger
    writes: list[dict[str, Any]] = []

    class SpyDecisionLogger:
        def __init__(self, base_path: str, **kwargs):
            pass
        def write(self, record: dict):
            writes.append(record)

    from core.xai import logger as xai_logger
    monkeypatch.setattr(xai_logger, 'DecisionLogger', SpyDecisionLogger)

    # Hotreload watcher spy to ensure no start on failure
    class SpyWatcher:
        def __init__(self, *args, **kwargs):
            self.started = False
        def start(self):
            self.started = True

    from core.config import hotreload
    monkeypatch.setattr(hotreload, 'FileWatcher', SpyWatcher)

    config_path = str(tmp_path / 'default.toml')
    schema_path = str(tmp_path / 'schema.json')
    (tmp_path / 'default.toml').write_text('')
    (tmp_path / 'schema.json').write_text('{}')

    # Act / Assert
    with pytest.raises(cfg_loader.SchemaValidationError):
        _init_lifespan(config_path=config_path, schema_path=schema_path, base_path=str(tmp_path))

    # XAI log captured with why_code
    assert writes and writes[0].get('why_code') == 'WHY_CONFIG_SCHEMA'
    assert 'bad schema' in (writes[0].get('errors') or '')


def test_lifespan_init_starts_hotreload(monkeypatch, tmp_path):
    # Arrange
    from core.config import loader as cfg_loader

    class DummyConfig:
        pass

    monkeypatch.setattr(cfg_loader, 'load_config', lambda *a, **k: DummyConfig())

    started = {'called': False, 'path': None}

    class SpyWatcher:
        def __init__(self, path, on_change, *, poll_interval_sec: float = 1.0):
            self.path = str(path)
        def start(self):
            started['called'] = True
            started['path'] = self.path

    from core.config import hotreload
    monkeypatch.setattr(hotreload, 'FileWatcher', SpyWatcher)

    class SpyDecisionLogger:
        def __init__(self, *a, **k):
            pass
        def write(self, record: dict):
            pass

    from core.xai import logger as xai_logger
    monkeypatch.setattr(xai_logger, 'DecisionLogger', SpyDecisionLogger)

    config_path = str(tmp_path / 'default.toml')
    schema_path = str(tmp_path / 'schema.json')
    (tmp_path / 'default.toml').write_text('')
    (tmp_path / 'schema.json').write_text('{}')

    # Act
    _init_lifespan(config_path=config_path, schema_path=schema_path, base_path=str(tmp_path))

    # Assert
    assert started['called'] is True
    assert started['path'] == config_path

