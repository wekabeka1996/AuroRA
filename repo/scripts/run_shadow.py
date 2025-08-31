"""
This runner has been archived. 'shadow' runtime mode is removed.
If you need the original script, see `archive/legacy/run_shadow.py`.
Executing this shim will raise an informative RuntimeError.
"""
import sys

def main():
    raise RuntimeError("'shadow' runner removed; historical copy available in archive/legacy/run_shadow.py")

if __name__ == '__main__':
    main()