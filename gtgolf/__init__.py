"""GT Golf Club package.

``golf.py`` is the command-line entry point. This package holds the pieces:

- ``config`` week settings, picks, and the points tables
- ``api`` SportsData.io client
- ``profiles`` cached golfer and headshot files
- ``scoring`` place-to-points and leaderboard ranking
- ``db`` SQLite schema and queries
- ``tee_times`` Eastern-to-Pacific clock display
- ``leaderboard`` the sleeping live-update loop
- ``optimizer`` DraftKings salary-cap search
- ``web`` Flask routes
- ``cli`` argument parsing and command dispatch
"""

from gtgolf import config
from gtgolf.api import (
    api_get_all_players,
    api_get_all_tournaments,
    api_get_dfs_slates,
    api_get_headshots,
    api_get_leaderboard,
    api_get_projections,
    api_request,
)
from gtgolf.db import (
    add_pick,
    add_picks,
    create_leaderboard_table,
    create_picks_table,
    create_salaries_table,
    create_tournaments_table,
    db_connection,
    get_db_connection,
    get_leaderboard,
    get_picks,
    get_salaries,
    get_tournament_from_id,
    get_tournaments,
    populate_salaries_table,
    populate_tournaments_table,
    update_leaderboard,
)
from gtgolf.leaderboard import manage_leaderboard, update_picks
from gtgolf.optimizer import (
    Roster,
    autopick,
    get_players,
    get_roster,
    get_starting_roster,
    points,
    values,
)
from gtgolf.profiles import (
    fetch_headshots,
    fetch_player_profiles,
    get_player_id_from_name,
    get_player_profile,
    load_headshots,
    load_player_profiles,
)
from gtgolf.scoring import get_points, parse_leaderboard
from gtgolf.tee_times import (
    annotate_leaderboard,
    convert_tee_time,
    get_first_tee_time,
    get_last_tee_time,
    get_last_updated_str,
    get_seconds_since_tee_time,
    get_time_str,
)
from gtgolf.web import app, get_player_standing, index, results, tournaments
from gtgolf.cli import main, parse_args

__all__ = [
    'Roster',
    'add_pick',
    'add_picks',
    'annotate_leaderboard',
    'api_get_all_players',
    'api_get_all_tournaments',
    'api_get_dfs_slates',
    'api_get_headshots',
    'api_get_leaderboard',
    'api_get_projections',
    'api_request',
    'app',
    'autopick',
    'config',
    'convert_tee_time',
    'create_leaderboard_table',
    'create_picks_table',
    'create_salaries_table',
    'create_tournaments_table',
    'db_connection',
    'fetch_headshots',
    'fetch_player_profiles',
    'get_db_connection',
    'get_first_tee_time',
    'get_last_tee_time',
    'get_last_updated_str',
    'get_leaderboard',
    'get_picks',
    'get_player_id_from_name',
    'get_player_profile',
    'get_player_standing',
    'get_players',
    'get_points',
    'get_roster',
    'get_salaries',
    'get_seconds_since_tee_time',
    'get_starting_roster',
    'get_time_str',
    'get_tournament_from_id',
    'get_tournaments',
    'index',
    'load_headshots',
    'load_player_profiles',
    'main',
    'manage_leaderboard',
    'parse_args',
    'parse_leaderboard',
    'points',
    'populate_salaries_table',
    'populate_tournaments_table',
    'results',
    'tournaments',
    'update_leaderboard',
    'update_picks',
    'values',
]
