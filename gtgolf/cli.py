"""Command-line dispatch for ``python golf.py``.

The ``cmd`` help text is still ``Directory path``. That string is what
``--help`` printed before the package split.
"""

import argparse
from pprint import pprint

from gtgolf import api, config, db, leaderboard, optimizer, profiles
from gtgolf.web import app


def parse_args():
    """Parse the subcommand and the optional round or roster count.

    Returns:
        ``argparse.Namespace`` with ``cmd``, ``round_num``, and ``num_rosters``.
    """
    description = 'Fantasy Golf Tool'
    parser = argparse.ArgumentParser(description=description, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument('cmd', help='Directory path', type=str, choices=config.CMDS)
    parser.add_argument('-r', '--round-num', help='Round number', type=int, default=1)
    parser.add_argument('-n', '--num-rosters', help='Number of rosters', type=int, default=1)
    return parser.parse_args()


def sandbox():
    """Print the headshot feed. This command calls the network."""
    pprint(api.api_get_headshots())


def main():
    """Dispatch ``sys.argv`` to one command."""
    args = parse_args()
    command = args.cmd
    tournament_id = config.TOURNAMENT_ID

    if command == 'players':
        profiles.fetch_player_profiles()
    elif command == 'create-leaderboard-table':
        db.create_leaderboard_table()
    elif command == 'manage-leaderboard':
        leaderboard.manage_leaderboard(tournament_id, args.round_num)
    elif command == 'update-leaderboard':
        db.update_leaderboard(tournament_id)
    elif command == 'tournaments':
        db.create_tournaments_table()
        db.populate_tournaments_table()
    elif command == 'salaries':
        db.create_salaries_table()
        db.populate_salaries_table(tournament_id)
    elif command == 'autopick':
        optimizer.autopick(tournament_id, args.num_rosters)
    elif command == 'values':
        optimizer.values(tournament_id)
    elif command == 'points':
        optimizer.points(tournament_id)
    elif command == 'picks':
        leaderboard.update_picks()
    elif command == 'clear-picks':
        db.create_picks_table()
        db.update_leaderboard(tournament_id)
    elif command == 'flask':
        app.run(host='0.0.0.0', port=80, debug=True)
    elif command == 'sandbox':
        sandbox()
