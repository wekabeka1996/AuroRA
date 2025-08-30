# Ensure project root is on sys.path for tests
import sys
import pathlib
# Add repository root to sys.path (parent of test folder)
repo_root = pathlib.Path(__file__).parent.resolve().parent
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))
