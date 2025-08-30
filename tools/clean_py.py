import sys
import pathlib
import unicodedata

# Default to current directory if no argument provided
root = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else '.')

def clean_text(s: str) -> str:
    # Remove control characters except tab/newline/carriage return
    cleaned = ''.join(ch for ch in s if (ch in '\t\n\r' or (unicodedata.category(ch)[0] != 'C')))
    # Replace non-breaking and other separator spaces with normal space
    cleaned = ''.join(' ' if (unicodedata.category(ch) == 'Zs' and ch != ' ') else ch for ch in cleaned)
    # Normalize line endings to \n
    cleaned = cleaned.replace('\r\n', '\n').replace('\r', '\n')
    return cleaned

for path in root.rglob('*.py'):
    raw = path.read_text(encoding='utf-8', errors='ignore')
    new = clean_text(raw)
    if new != raw:
        path.write_text(new, encoding='utf-8')
        print(f'Cleaned {path}')
print('Done')
