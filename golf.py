#!/usr/bin/env python3
"""Command-line entry point for the GT Golf Club fantasy pool.

Five owners each pick six golfers. Finishing position becomes pool points, and
``python golf.py flask`` serves the standings site. The implementation lives
in the ``gtgolf`` package. Edit ``gtgolf/config.py`` to change the tournament,
the picks, or the API key, then run ``python golf.py --help``.
"""

from datetime import datetime, timedelta

from gtgolf.api import (
    api_get_all_players,
    api_get_all_tournaments,
    api_get_dfs_slates,
    api_get_headshots,
    api_get_leaderboard,
    api_get_projections,
    api_request,
)
from gtgolf.cli import main, parse_args
from gtgolf.config import (
    BASE_URL,
    CMDS,
    DATABASE,
    HEADSHOTS_FILENAME,
    KEY,
    LEADERBOARD_UPDATE_PERIOD,
    MAJOR,
    MAJOR_MULTIPLIER,
    MAX_SALARY,
    NUM_PICKS,
    ONE_N_DONE_POINTS,
    ONE_N_DONES,
    OWNERS,
    PICKS,
    PLAYERS_FILENAME,
    POINTS,
    ROUND_END_SLEEP_PERIOD,
    TOURNAMENT_ID,
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

if __name__ == '__main__':
    main()
