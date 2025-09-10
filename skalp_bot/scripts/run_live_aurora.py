import sys

from skalp_bot.runner.run_live_aurora import main

if __name__ == '__main__':
    cfg_path = sys.argv[1] if len(sys.argv) > 1 else None
    main(cfg_path)
