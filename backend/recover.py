"""Inspect or explicitly recover a stale reservation using an exported DATABASE_URL."""
import argparse
import getpass
import json
import sys

import psycopg

from . import db


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command')
    commands.add_parser('inspect', help='Show occupied slots and their recovery eligibility (default).')
    recover = commands.add_parser('recover', help='Recover one stale slot after all old workers have stopped.')
    recover.add_argument('slot', choices=('processing', 'chat'))
    recover.add_argument('--all-workers-stopped', action='store_true', required=True,
                         help='Confirm that every worker that could still own the reservation has stopped.')
    args = parser.parse_args(argv)

    try:
        if args.command == 'recover':
            token = getpass.getpass('Owner token from inspection: ')
            db.recover_slot(args.slot, token, all_workers_stopped=args.all_workers_stopped)
            print(f'Recovered the {args.slot} reservation.')
        else:
            print(json.dumps(db.inspect_slots(), indent=2, default=str))
    except ValueError as error:
        print(f'Recovery refused. {error}', file=sys.stderr)
        return 1
    except (EOFError, KeyboardInterrupt):
        print('Recovery canceled.', file=sys.stderr)
        return 1
    except (RuntimeError, psycopg.Error):
        print('Database operation failed. Check the exported DATABASE_URL and application schema.', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
