import re
import os
from pathlib import Path

DOC_PATH = Path('docs') / 'Road_map.md'
# Use a more generic output directory
OUT_ROOT = Path('extracted_code')


def read_doc(path: Path) -> str:
    # Read with best-effort decoding
    data = path.read_bytes()
    for enc in ('utf-8', 'utf-8-sig', 'cp1251', 'latin-1'):
        try:
            return data.decode(enc)
        except Exception:
            continue
    # Fallback ignoring errors
    return data.decode('utf-8', errors='ignore')


def iter_code_blocks(md: str):
    # Match fenced code blocks with 3+ backticks. Capture the fence and language.
    # Then capture content non-greedily until matching fence length.
    # Example: ````python\n...\n````
    pattern = re.compile(r"(?s)(`{3,})([a-zA-Z0-9_+-]*)\r?\n(.*?)(?:\r?\n\1)\s*")
    for m in pattern.finditer(md):
        fence, lang, content = m.groups()
        yield lang.lower(), content


def derive_target_path(first_line: str) -> Path | None:
    # Expect comment like: # core/features/microstructure.py
    # or // path for other languages; handle leading markers.
    line = first_line.strip()
    # Strip common comment tokens
    for prefix in ('#', '//', ';', '--'):
        if line.startswith(prefix):
            line = line[len(prefix):].strip()
            break
    # If it still contains '.py' or other extension and slashes, accept
    if ('.' in line) and ('/' in line or '\\' in line):
        return Path(line.replace('\\', '/'))
    return None


def main():
    if not DOC_PATH.exists():
        raise SystemExit(f"Missing {DOC_PATH}")

    md = read_doc(DOC_PATH)
    OUT_ROOT.mkdir(parents=True, exist_ok=True)

    written: list[Path] = []
    skipped_blocks = 0

    for lang, content in iter_code_blocks(md):
        if lang not in {"python", "yaml", "yml", "toml", "json", "ini", "text", "md"}:
            # Focus on likely source/config blocks
            continue

        lines = content.splitlines()
        if not lines:
            continue
        target = derive_target_path(lines[0])
        if not target:
            skipped_blocks += 1
            continue

        out_path = OUT_ROOT / target
        out_path.parent.mkdir(parents=True, exist_ok=True)

        # Preserve original content; write as-is
        out_path.write_text(content, encoding='utf-8')
        written.append(out_path)

    # Write a summary file
    summary = OUT_ROOT / 'EXTRACTION_SUMMARY.md'
    lines = [
        '# Extraction Summary',
        '',
        f'Source: {DOC_PATH}',
        f'Files written: {len(written)}',
        f'Skipped blocks (no path header or unsupported lang): {skipped_blocks}',
        '',
        '## Files',
    ]
    for p in sorted(written):
        lines.append(f'- {p.relative_to(OUT_ROOT)}')
    summary.write_text('\n'.join(lines) + '\n', encoding='utf-8')

    print(f"Wrote {len(written)} files under {OUT_ROOT}")


if __name__ == '__main__':
    main()
