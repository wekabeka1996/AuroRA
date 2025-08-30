import sys
import pathlib
import py_compile

# Default to current directory if no argument provided
root = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else '.')
errors = []
for path in root.rglob('*.py'):
    try:
        py_compile.compile(str(path), doraise=True)
        print(f'OK {path}')
    except py_compile.PyCompileError as e:
        print(f'ERR {path}: {e.msg}')
        errors.append(path)

if errors:
    sys.exit(1)
