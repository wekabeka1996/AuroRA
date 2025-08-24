# Ensure project root is on sys.path for tests
import sys
import pathlib
root = pathlib.Path(__file__).parent.resolve()
if str(root) not in sys.path:
    sys.path.insert(0, str(root))
