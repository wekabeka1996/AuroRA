import json, os, threading
from living_latent.core.utils.blackbox import blackbox_emit, _BLACKBOX_PATH  # type: ignore

def test_blackbox_emits_lines(tmp_path, monkeypatch):
    # Redirect path
    target = tmp_path / 'blackbox.jsonl'
    monkeypatch.setenv('PYTHONHASHSEED','0')
    # Monkeypatch module-level path
    import importlib
    mod = importlib.import_module('living_latent.core.utils.blackbox')
    mod._BLACKBOX_PATH = str(target)

    for i in range(10):
        blackbox_emit('evt', {'i': i})

    lines = target.read_text(encoding='utf-8').strip().splitlines()
    assert len(lines) == 10
    # Validate JSON
    for idx, line in enumerate(lines):
        rec = json.loads(line)
        assert rec['event'] == 'evt'
        assert rec['payload']['i'] == idx


def test_blackbox_thread_safety(tmp_path):
    import importlib
    mod = importlib.import_module('living_latent.core.utils.blackbox')
    mod._BLACKBOX_PATH = str(tmp_path / 'bb_thread.jsonl')

    def worker(offset):
        for j in range(50):
            blackbox_emit('w', {'k': offset*100 + j})

    threads = [threading.Thread(target=worker, args=(t,)) for t in range(4)]
    for t in threads: t.start()
    for t in threads: t.join()

    lines = (tmp_path / 'bb_thread.jsonl').read_text(encoding='utf-8').strip().splitlines()
    assert len(lines) == 200
    seen = set()
    for line in lines:
        data = json.loads(line)
        seen.add(data['payload']['k'])
    assert len(seen) == 200
