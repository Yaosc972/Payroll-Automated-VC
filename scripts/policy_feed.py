"""Run with python3 -m scripts.policy_feed migrate|refresh [--db /local/path]."""
import argparse
import json
from pathlib import Path
from bonus_platform.engine.policy import feed

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['migrate', 'refresh'])
    parser.add_argument('--db', type=Path)
    parser.add_argument('--all', action='store_true', help='Refresh all configured feeds locally; default rotates at most 8 feeds.')
    args = parser.parse_args()
    result = feed.migrate(args.db) if args.command == 'migrate' else feed.refresh(args.db, sources=feed.SOURCES if args.all else None)
    print(json.dumps(result or {'migrated': True}, ensure_ascii=False))
