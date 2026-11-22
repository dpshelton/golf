#!/usr/bin/env python3
"""Fantasy golf pool for the GT Golf Club.

Five owners (Ben, Greg, Mike, Don, and Sean) each take a lineup of PGA Tour
golfers for the tournament in ``TOURNAMENT_ID``. Finishing position becomes
pool points, and those points are doubled when ``MAJOR`` is true. A Flask site
shows live standings. The command line refreshes SportsData.io data into
SQLite and can search DraftKings lineups under the salary cap.

Edit the constants below to change the week, the picks, or the API key, then
run ``python golf.py --help`` for the command list.
"""

import argparse
import json
import os
import random
import sqlite3
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timedelta
from pprint import pprint

import requests
from flask import Flask, render_template
from prettytable import PrettyTable


def _adapt_datetime(value):
    """Store datetimes with a space separator, matching the legacy sqlite3 adapter.

    Args:
        value: A ``datetime`` written into SQLite.

    Returns:
        ISO-like text such as ``2024-01-25 08:20:20.335550``.
    """
    return value.isoformat(sep=' ')


# Register an explicit adapter so Python 3.12 does not warn, without changing
# the text already stored in LeaderboardLastUpdated.
sqlite3.register_adapter(datetime, _adapt_datetime)

# SportsData.io tournament currently shown on the site and used by the CLI.
TOURNAMENT_ID = 585
# Double pool points for a major championship.
MAJOR = False

MAX_SALARY = 50000
NUM_PICKS = 6

# Hand-entered lineups for the current tournament. Names must match DraftKingsName.
PICKS = {
    'Ben': [
        'Max Homa',
        'Jason Day',
        'Min Woo Lee',
        'Sam Stevens',
        'Luke List',
        'Charley Hoffman',
    ],
    'Greg': [
        'Harris English',
        'Sahith Theegala',
        'Jason Day',
        'Tony Finau',
        'Sam Stevens',
        'Jhonattan Vegas',
    ],
    'Mike': [
        'Collin Morikawa',
        'Sungjae Im',
        'Taylor Montgomery',
        'Luke List',
        'Sam Ryder',
        'Akshay Bhatia',
    ],
    'Don': [
        'Patrick Cantlay',
        'Emiliano Grillo',
        'Chez Reavie',
        'Daniel Berger',
        'Adam Schenk',
        'Collin Morikawa',
    ],
    'Sean': [
        'Max Homa',
        'Sahith Theegala',
        'Ludvig Aberg',
        'Sepp Straka',
        'Joel Dahmen',
        'Andrew Novak',
    ],
}

# One-and-done golfers are not inserted. ``add_picks`` ignores this map until
# that scoring path is turned back on.
ONE_N_DONES = {
    'Ben': '',
    'Greg': '',
    'Mike': '',
    'Don': '',
    'Sean': '',
}

# SportsData.io key. The app reads it from this constant.
KEY = 'a478d29a98e54eac8e9ebf1f218dd0b8'

PLAYERS_FILENAME = 'player_profiles.json'
HEADSHOTS_FILENAME = 'headshots.json'
# Overridden in tests. The CLI and the website use the file next to this module.
DATABASE = 'database.db'
LEADERBOARD_UPDATE_PERIOD = 10 * 60
ROUND_END_SLEEP_PERIOD = 1 * 60 * 60
MAJOR_MULTIPLIER = 2

CMDS = [
    'players',
    'manage-leaderboard',
    'update-leaderboard',
    'create-leaderboard-table',
    'tournaments',
    'picks',
    'clear-picks',
    'sandbox',
    'flask',
    'salaries',
    'autopick',
    'values',
    'points',
]

# (first place, last place, points). A later band starts where the previous one
# stopped, and places 61 through 1000 all score 3.
POINTS = [
    (1, 1, 150),
    (2, 2, 75),
    (3, 3, 50),
    (4, 4, 35),
    (5, 5, 30),
    (6, 6, 25),
    (7, 7, 20),
    (8, 8, 18),
    (9, 9, 16),
    (10, 10, 14),
    (11, 15, 12),
    (16, 20, 10),
    (21, 25, 8),
    (26, 30, 7),
    (31, 40, 6),
    (41, 50, 5),
    (51, 60, 4),
    (61, 1000, 3),
]

# Shorter table used only for a one-and-done golfer. Places past 10 score 0.
ONE_N_DONE_POINTS = [
    (1, 1, 50),
    (2, 2, 25),
    (3, 3, 15),
    (4, 4, 12),
    (5, 5, 10),
    (6, 6, 8),
    (7, 7, 6),
    (8, 8, 5),
    (9, 9, 4),
    (10, 10, 3),
]

OWNERS = [
    'Ben',
    'Greg',
    'Mike',
    'Don',
    'Sean',
]

BASE_URL = 'https://api.sportsdata.io'

# Columns shared by the four tournament lists. Date text is trimmed to a day.
_TOURNAMENT_LIST_SQL = '''
    SELECT
        TournamentID,
        Name,
        strftime("%Y-%m-%d", "StartDate") as StartDate,
        strftime("%Y-%m-%d", "EndDate") as EndDate,
        Location,
        Venue
    FROM tournaments
    WHERE {where_clause}
    ORDER BY {order_clause}
'''

_INDEX_SQL = {
    'leaderboards': (
        'CREATE INDEX IF NOT EXISTS idx_leaderboards_tournament_player ON leaderboards (TournamentID, PlayerID)',
        'CREATE INDEX IF NOT EXISTS idx_leaderboards_tournament_position ON leaderboards (TournamentID, Position)',
    ),
    'salaries': (
        'CREATE INDEX IF NOT EXISTS idx_salaries_tournament ON salaries (TournamentID)',
    ),
    'picks': (
        'CREATE INDEX IF NOT EXISTS idx_picks_owner_tournament ON picks (Owner, TournamentID)',
    ),
    'tournaments': (
        'CREATE INDEX IF NOT EXISTS idx_tournaments_tournament_id ON tournaments (TournamentID)',
    ),
}

app = Flask(__name__)
# One session so repeated leaderboard polls reuse the TCP connection.
_session = requests.Session()
# path -> (mtime_ns, size), parsed JSON. Profiles are several megabytes.
_json_cache = {}
# id(profile_list) -> (list, indexes). Invalidated when a new list is loaded.
_profile_index_cache = {}


def _rank_points_lookup(table):
    """Expand inclusive place bands into a rank-to-points map.

    Args:
        table: Sequence of ``(start, end, points)`` bands.

    Returns:
        Dict mapping every integer rank in those bands to its points.
    """
    lookup = {}
    for start, end, points in table:
        for rank in range(start, end + 1):
            lookup[rank] = points
    return lookup


_POINTS_BY_RANK = _rank_points_lookup(POINTS)
_ONE_AND_DONE_BY_RANK = _rank_points_lookup(ONE_N_DONE_POINTS)


class Roster:
    """A lineup plus its projected fantasy points and DraftKings salary.

    Players are kept highest salary first so the printed form is stable.
    """

    def __init__(self, players):
        """Store ``players`` sorted by salary and cache the two totals.

        Args:
            players: Mappings with ``FantasyPoints``, ``DraftKingsSalary``,
                ``DraftKingsName``, and ``Value``.
        """
        self.players = sorted(players, key=lambda player: player['DraftKingsSalary'], reverse=True)
        self.total_points = self.get_total_points()
        self.total_salary = self.get_total_salary()

    def get_total_points(self):
        """Return the sum of projected fantasy points.

        Returns:
            Numeric total, or 0 for an empty lineup.
        """
        return sum(player['FantasyPoints'] for player in self.players)

    def get_total_salary(self):
        """Return the sum of DraftKings salaries.

        Returns:
            Integer salary total, or 0 for an empty lineup.
        """
        return sum(player['DraftKingsSalary'] for player in self.players)

    def __str__(self):
        """Return the multi-line lineup used by ``autopick``."""
        lines = [
            'Points: {:.3f}, Salary: {:5}'.format(self.total_points, self.total_salary),
        ]
        for player in self.players:
            lines.append('    {:30}, Points: {:.3f}, Salary: {:5}, Value: {:.3f}'.format(
                player['DraftKingsName'],
                player['FantasyPoints'],
                player['DraftKingsSalary'],
                player['Value'],
            ))
        return '\n'.join(lines) + '\n'


def parse_args():
    """Parse the subcommand and the optional round or roster count.

    Returns:
        ``argparse.Namespace`` with ``cmd``, ``round_num``, and ``num_rosters``.
    """
    description = 'Fantasy Golf Tool'
    parser = argparse.ArgumentParser(description=description, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument('cmd', help='Directory path', type=str, choices=CMDS)
    parser.add_argument('-r', '--round-num', help='Round number', type=int, default=1)
    parser.add_argument('-n', '--num-rosters', help='Number of rosters', type=int, default=1)
    return parser.parse_args()


def api_request(url):
    """GET a SportsData.io URL and parse the JSON body.

    Args:
        url: Absolute endpoint, without the ``key`` query parameter.

    Returns:
        The decoded JSON value, usually a list or a dict.

    Raises:
        requests.RequestException: The HTTP call failed.
        json.JSONDecodeError: The body was not JSON.
    """
    response = _session.get(url, params={'key': KEY})
    return json.loads(response.text)


def api_get_all_players():
    """Download every golfer profile.

    Returns:
        List of player profile objects.
    """
    print('API-CALL: api_get_all_players')
    return api_request(BASE_URL + '/golf/v2/json/Players')


def api_get_all_tournaments():
    """Download the tournament calendar.

    Returns:
        List of tournament objects.
    """
    print('API-CALL: api_get_all_tournaments')
    return api_request(BASE_URL + '/golf/v2/json/Tournaments')


def api_get_leaderboard(tournament_id):
    """Download one tournament leaderboard.

    Args:
        tournament_id: SportsData tournament id.

    Returns:
        Leaderboard object with ``Tournament`` and ``Players``.
    """
    print('API-CALL: api_get_leaderboard')
    return api_request(BASE_URL + '/golf/v2/json/Leaderboard/{}'.format(tournament_id))


def api_get_projections(tournament_id):
    """Download fantasy projections for one tournament.

    Args:
        tournament_id: SportsData tournament id.

    Returns:
        List of projection objects.
    """
    print('API-CALL: api_get_projections')
    return api_request(BASE_URL + '/golf/v2/json/PlayerTournamentProjectionStats/{}'.format(tournament_id))


def api_get_dfs_slates(tournament_id):
    """Download daily-fantasy slates, including DraftKings salaries.

    Args:
        tournament_id: SportsData tournament id.

    Returns:
        List of slate objects.
    """
    print('API-CALL: api_get_dfs_slates')
    return api_request(BASE_URL + '/golf/v2/json/DfsSlatesByTournament/{}'.format(tournament_id))


def api_get_headshots():
    """Download hosted headshot URLs.

    Returns:
        List of headshot objects.
    """
    print('API-CALL: api_get_headshots')
    return api_request(BASE_URL + '/v3/golf/headshots/json/Headshots')


def _profile_indexes(player_profiles):
    """Index profiles by id and DraftKings name, keeping the first duplicate.

    The first match is the one a forward scan would return. DraftKings names
    are not unique (two ``Jamal Hossain`` rows, for example).

    Args:
        player_profiles: Profile mappings.

    Returns:
        Dict with ``by_player_id``, ``by_dk_id``, and ``by_name``.
    """
    cached = _profile_index_cache.get(id(player_profiles))
    if cached is not None and cached[0] is player_profiles:
        return cached[1]

    by_player_id = {}
    by_dk_id = {}
    by_name = {}
    for profile in player_profiles:
        by_player_id.setdefault(profile['PlayerID'], profile)
        dk_id = profile['DraftKingsPlayerID']
        if dk_id is not None:
            by_dk_id.setdefault(dk_id, profile)
        # None names are indexed too, so a lookup for None still returns the first.
        by_name.setdefault(profile['DraftKingsName'], profile)

    indexes = {
        'by_player_id': by_player_id,
        'by_dk_id': by_dk_id,
        'by_name': by_name,
    }
    _profile_index_cache[id(player_profiles)] = (player_profiles, indexes)
    return indexes


def get_player_profile(player_id=None, draft_kings_player_id=None, player_profiles=None):
    """Find one profile by SportsData id, DraftKings id, or either.

    When both ids are passed, the earliest profile in ``player_profiles`` that
    matches either id wins. That is the same rule as scanning the list once.

    Args:
        player_id: SportsData ``PlayerID``, or None to skip that key.
        draft_kings_player_id: DraftKings id, or None to skip that key.
        player_profiles: Profile mappings to search.

    Returns:
        The matching profile, or None when neither id hits.
    """
    if player_id is not None and draft_kings_player_id is not None:
        for profile in player_profiles:
            if player_id == profile['PlayerID'] or draft_kings_player_id == profile['DraftKingsPlayerID']:
                return profile
        return None

    indexes = _profile_indexes(player_profiles)
    if player_id is not None:
        return indexes['by_player_id'].get(player_id)
    if draft_kings_player_id is not None:
        return indexes['by_dk_id'].get(draft_kings_player_id)
    return None


def get_player_id_from_name(player_name, player_profiles):
    """Resolve a DraftKings display name to a SportsData player id.

    Args:
        player_name: ``DraftKingsName``. The first row wins when names repeat.
        player_profiles: Profile mappings to search.

    Returns:
        ``PlayerID``, or None when the name is absent.
    """
    profile = _profile_indexes(player_profiles)['by_name'].get(player_name)
    if profile is None:
        return None
    return profile['PlayerID']


def get_points(rank, one_n_done=False, major=False):
    """Convert a finishing position into pool points.

    Args:
        rank: 1-based place, or None when the golfer has no score. Integer
            ranks use a precomputed table. Other numbers, including ``True``,
            still walk the inclusive bands.
        one_n_done: Use ``ONE_N_DONE_POINTS`` instead of ``POINTS``.
        major: Multiply the award by ``MAJOR_MULTIPLIER``.

    Returns:
        Point value. Missing ranks and places outside the table score 0.
    """
    multiplier = MAJOR_MULTIPLIER if major else 1
    if rank is None:
        return 0
    # bool is a subclass of int, but type(True) is bool. Keep the old band walk
    # for those values so True still scores like a first-place finish.
    if type(rank) is int:
        table = _ONE_AND_DONE_BY_RANK if one_n_done else _POINTS_BY_RANK
        return table.get(rank, 0) * multiplier

    bands = ONE_N_DONE_POINTS if one_n_done else POINTS
    for start, end, points in bands:
        if start <= rank <= end:
            return points * multiplier
    return 0


def _leaderboard_row(player, profile, rank):
    """Build one stored leaderboard record.

    Args:
        player: Raw leaderboard player from the API.
        profile: Matching profile. Missing profiles raise, as they always did.
        rank: Integer place, or None.

    Returns:
        Mapping ready to insert. Missing scores and tee times become the
        string ``"None"`` so the templates can compare against that sentinel.
    """
    return {
        'PlayerID': player['PlayerID'],
        'Rank': str(rank),
        'DraftKingsPlayerID': profile['DraftKingsPlayerID'],
        'DraftKingsName': profile['DraftKingsName'],
        'Points': str(get_points(rank, one_n_done=False, major=MAJOR)),
        'OneAndDonePoints': str(get_points(rank, one_n_done=True, major=MAJOR)),
        'TotalThrough': player['TotalThrough'] if player['TotalThrough'] is not None else 'None',
        'TeeTime': player['TeeTime'] if player['TeeTime'] is not None else 'None',
    }


def parse_leaderboard(leaderboard, player_profiles):
    """Turn a SportsData leaderboard into pool rows.

    The feed's own rank is not used. Golfers who have a total score keep the
    API's order and take competition ranking: a tie keeps the place of the
    first golfer with that score, and the next different score skips the
    tied places. Golfers with no score are appended afterward as rank
    ``"None"``, even if they sat between scored golfers in the feed.

    Args:
        leaderboard: Leaderboard JSON object. ``Players`` must already be grouped
            so equal scores are adjacent; this function does not re-sort.
        player_profiles: Profiles that supply DraftKings ids and names.

    Returns:
        Ranked rows followed by unranked rows.
    """
    by_id = _profile_indexes(player_profiles)['by_player_id']
    ranked = []
    unranked = []
    ranked_player_count = 0
    previous_score = None
    current_rank = 1

    for player in leaderboard['Players']:
        profile = by_id.get(player['PlayerID'])
        if player['TotalScore'] is not None:
            ranked_player_count += 1
            if player['TotalScore'] != previous_score:
                current_rank = ranked_player_count
            previous_score = player['TotalScore']
            ranked.append(_leaderboard_row(player, profile, current_rank))
        else:
            unranked.append(_leaderboard_row(player, profile, None))

    return ranked + unranked


def _load_json(path):
    """Read JSON from ``path``, reusing the parse while the file is unchanged.

    Args:
        path: Filesystem path.

    Returns:
        The decoded JSON value. Callers must treat a cached list as read-only.
    """
    stat_result = os.stat(path)
    cache_key = (stat_result.st_mtime_ns, stat_result.st_size)
    cached = _json_cache.get(path)
    if cached is not None and cached[0] == cache_key:
        return cached[1]
    with open(path, 'r', encoding='utf-8') as handle:
        payload = json.load(handle)
    _json_cache[path] = (cache_key, payload)
    return payload


def _write_json(path, payload):
    """Write ``payload`` as compact JSON and refresh the read cache.

    Args:
        path: Destination path. The file is replaced in place.
        payload: JSON-serializable value.
    """
    with open(path, 'w', encoding='utf-8') as handle:
        json.dump(payload, handle)
    stat_result = os.stat(path)
    _json_cache[path] = ((stat_result.st_mtime_ns, stat_result.st_size), payload)


def fetch_player_profiles():
    """Download every profile and overwrite ``player_profiles.json``.

    Returns:
        The profile list that was written.
    """
    player_profiles = api_get_all_players()
    _write_json(PLAYERS_FILENAME, player_profiles)
    return player_profiles


def load_player_profiles():
    """Load ``player_profiles.json``.

    Returns:
        List of profile mappings. Repeated calls return the same list until
        the file changes.
    """
    return _load_json(PLAYERS_FILENAME)


def fetch_headshots():
    """Download headshots and overwrite ``headshots.json``.

    Returns:
        The headshot list that was written.
    """
    headshots = api_get_headshots()
    _write_json(HEADSHOTS_FILENAME, headshots)
    return headshots


def load_headshots():
    """Load ``headshots.json``.

    Returns:
        List of headshot mappings.
    """
    return _load_json(HEADSHOTS_FILENAME)


def _ensure_indexes(connection):
    """Create lookup indexes for tables that already exist.

    Args:
        connection: Open SQLite connection. DDL commits any open transaction.
    """
    present = {
        row[0]
        for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    for table, statements in _INDEX_SQL.items():
        if table not in present:
            continue
        for statement in statements:
            connection.execute(statement)


def get_db_connection():
    """Open SQLite with row access by column name.

    Returns:
        Connection to ``DATABASE``. The caller must close it.
    """
    connection = sqlite3.connect(DATABASE)
    connection.row_factory = sqlite3.Row
    _ensure_indexes(connection)
    return connection


@contextmanager
def db_connection():
    """Yield a connection and always close it.

    Callers commit their own writes. Closing without a commit rolls an open
    transaction back.

    Yields:
        sqlite3.Connection
    """
    connection = get_db_connection()
    try:
        yield connection
    finally:
        connection.close()


def create_tournaments_table():
    """Drop and recreate the tournament calendar table."""
    with db_connection() as connection:
        connection.execute('DROP TABLE IF EXISTS tournaments;')
        connection.execute('''
            CREATE TABLE tournaments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                TournamentID INTEGER NOT NULL,
                Name TEXT NOT NULL,
                StartDate TEXT NOT NULL,
                EndDate TEXT NOT NULL,
                Location TEXT,
                Venue TEXT,
                LeaderboardLastUpdated TEXT
            );
        ''')
        _ensure_indexes(connection)
        connection.commit()


def populate_tournaments_table():
    """Insert every tournament returned by the API.

    The ``tournaments`` command drops the table first. This function only
    inserts, so running it alone appends another copy of the calendar.
    """
    tournaments = api_get_all_tournaments()
    rows = [
        (
            tournament['TournamentID'],
            tournament['Name'],
            tournament['StartDate'],
            tournament['EndDate'],
            tournament['Location'],
            tournament['Venue'],
        )
        for tournament in tournaments
    ]
    with db_connection() as connection:
        connection.executemany(
            'INSERT INTO tournaments (TournamentID, Name, StartDate, EndDate, Location, Venue) VALUES (?, ?, ?, ?, ?, ?)',
            rows,
        )
        connection.commit()


def create_salaries_table():
    """Drop and recreate the DraftKings salary table."""
    with db_connection() as connection:
        connection.execute('DROP TABLE IF EXISTS salaries;')
        connection.execute('''
            CREATE TABLE salaries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                TournamentID INTEGER,
                PlayerID INTEGER,
                DraftKingsPlayerID INTEGER,
                DraftKingsName TEXT,
                DraftKingsSalary INTEGER,
                FantasyPoints REAL
            );
        ''')
        _ensure_indexes(connection)
        connection.commit()


def populate_salaries_table(tournament_id):
    """Load DraftKings salaries and projections for ``tournament_id``.

    The first DraftKings slate is the one that is stored. Golfers who are not
    in the local profile file are skipped and named on stdout.

    Args:
        tournament_id: SportsData tournament id. Both the API calls and the
            inserted rows use this id.
    """
    tournament = get_tournament_from_id(tournament_id)
    if tournament is None:
        return

    profiles = _profile_indexes(load_player_profiles())['by_player_id']
    fantasy_points = {}
    for projection in api_get_projections(tournament_id):
        fantasy_points[projection['PlayerID']] = projection['FantasyPoints']

    rows = []
    for dfs_slate in api_get_dfs_slates(tournament_id):
        if dfs_slate['Operator'] != 'DraftKings':
            continue
        for player in dfs_slate['DfsSlatePlayers']:
            profile = profiles.get(player['PlayerID'])
            if profile is None:
                print('WTF {}'.format(player['OperatorPlayerName']))
                continue
            rows.append((
                tournament_id,
                profile['PlayerID'],
                profile['DraftKingsPlayerID'],
                profile['DraftKingsName'],
                player['OperatorSalary'],
                fantasy_points.get(profile['PlayerID'], 0),
            ))
        break

    if not rows:
        return

    with db_connection() as connection:
        connection.executemany(
            '''INSERT INTO salaries (
                TournamentID, PlayerID, DraftKingsPlayerID, DraftKingsName, DraftKingsSalary, FantasyPoints
            ) VALUES (?, ?, ?, ?, ?, ?)''',
            rows,
        )
        connection.commit()


def get_tournaments():
    """Split the calendar into active, upcoming, past, and nearby lists.

    Past events are limited to the last year. "Relevant" events are those
    that ended within two days or start within three weeks, which the retired
    picks page used as its dropdown.

    Returns:
        Four lists of sqlite rows: active, upcoming, past, relevant.
    """
    queries = (
        ("StartDate <= datetime('now') AND EndDate >= datetime('now')", 'StartDate'),
        ("StartDate > datetime('now')", 'StartDate'),
        ("EndDate < datetime('now') AND EndDate >= datetime('now', '-1 year')", 'EndDate DESC'),
        ("EndDate >= datetime('now', '-2 days') AND StartDate <= datetime('now', '+21 days')", 'EndDate'),
    )
    with db_connection() as connection:
        results = []
        for where_clause, order_clause in queries:
            sql = _TOURNAMENT_LIST_SQL.format(where_clause=where_clause, order_clause=order_clause)
            results.append(connection.execute(sql).fetchall())
    return tuple(results)


def get_tournament_from_id(tournament_id):
    """Return one tournament row, or None when the id is not stored.

    Args:
        tournament_id: SportsData tournament id.

    Returns:
        The first matching sqlite row, or None.
    """
    with db_connection() as connection:
        tournaments = connection.execute(
            'SELECT * FROM tournaments WHERE TournamentID == ?',
            (tournament_id,),
        ).fetchall()
    if not tournaments:
        return None
    return tournaments[0]


def get_salaries(tournament_id):
    """Return salaries for ``tournament_id``, fetching them if the table is empty.

    Args:
        tournament_id: SportsData tournament id.

    Returns:
        sqlite rows. Empty when the tournament itself is not in the database,
        because the fetch is skipped in that case.
    """
    query = 'SELECT * FROM salaries WHERE TournamentID == ?'
    with db_connection() as connection:
        salaries = connection.execute(query, (tournament_id,)).fetchall()
    if salaries:
        return salaries

    populate_salaries_table(tournament_id)
    with db_connection() as connection:
        return connection.execute(query, (tournament_id,)).fetchall()


def create_leaderboard_table():
    """Drop and recreate the per-tournament leaderboard table."""
    with db_connection() as connection:
        connection.execute('DROP TABLE IF EXISTS leaderboards;')
        connection.execute('''
            CREATE TABLE leaderboards (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                TournamentID INTEGER NOT NULL,
                PlayerID TEXT NOT NULL,
                Rank TEXT NOT NULL,
                DraftKingsPlayerID TEXT NOT NULL,
                DraftKingsName TEXT NOT NULL,
                Points TEXT NOT NULL,
                OneAndDonePoints TEXT NOT NULL,
                Position INTEGER NOT NULL,
                TotalThrough TEXT,
                TeeTime TEXT
            );
        ''')
        _ensure_indexes(connection)
        connection.commit()


def _known_player_ids(stored_ids):
    """Add int and text forms of stored player ids.

    Leaderboard ids are TEXT. The API sends integers. SQLite's type affinity
    treats those as the same golfer; this set does the same check in Python.

    Args:
        stored_ids: Player id values as SQLite returned them.

    Returns:
        Set containing each id and its integer form when it is numeric.
    """
    known = set()
    for stored in stored_ids:
        known.add(stored)
        known.add(str(stored))
        try:
            known.add(int(stored))
        except (TypeError, ValueError):
            continue
    return known


def _stored_text(value):
    """Replace a missing DraftKings field with the historical ``Unknown`` token.

    Args:
        value: Id or name from a profile.

    Returns:
        ``value``, or ``'Unknown'`` when it is None.
    """
    if value is None:
        return 'Unknown'
    return value


def update_leaderboard(tournament_id, leaderboard=None):
    """Insert or update pool rows for one tournament and stamp the refresh time.

    Args:
        tournament_id: SportsData tournament id.
        leaderboard: Optional leaderboard JSON. When omitted, the live feed
            is downloaded.
    """
    if leaderboard is None:
        leaderboard = api_get_leaderboard(tournament_id)
    parsed = parse_leaderboard(leaderboard, load_player_profiles())

    with db_connection() as connection:
        stored_ids = [
            row['PlayerID']
            for row in connection.execute(
                'SELECT PlayerID FROM leaderboards WHERE TournamentID == ?',
                (tournament_id,),
            )
        ]
        known_ids = _known_player_ids(stored_ids)
        inserts = []
        updates = []
        for position, player in enumerate(parsed):
            player_id = player['PlayerID']
            if player_id in known_ids or str(player_id) in known_ids:
                updates.append((
                    player['Rank'],
                    player['Points'],
                    player['OneAndDonePoints'],
                    position,
                    player['TotalThrough'],
                    player['TeeTime'],
                    tournament_id,
                    player_id,
                ))
            else:
                inserts.append((
                    tournament_id,
                    player_id,
                    player['Rank'],
                    _stored_text(player['DraftKingsPlayerID']),
                    _stored_text(player['DraftKingsName']),
                    player['Points'],
                    player['OneAndDonePoints'],
                    position,
                    player['TotalThrough'],
                    player['TeeTime'],
                ))
                known_ids.add(player_id)
                known_ids.add(str(player_id))

        # Insert before update so a golfer who appears twice in one feed is
        # written and then corrected, which is what the row-by-row loop did.
        connection.executemany(
            '''INSERT INTO leaderboards (
                TournamentID, PlayerID, Rank, DraftKingsPlayerID, DraftKingsName,
                Points, OneAndDonePoints, Position, TotalThrough, TeeTime
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            inserts,
        )
        connection.executemany(
            '''UPDATE leaderboards
                SET Rank=?, Points=?, OneAndDonePoints=?, Position=?, TotalThrough=?, TeeTime=?
                WHERE TournamentID==? AND PlayerID==?''',
            updates,
        )
        connection.execute(
            'UPDATE tournaments SET LeaderboardLastUpdated=? WHERE TournamentID=?',
            (datetime.now(), tournament_id),
        )
        connection.commit()


def get_leaderboard(tournament_id):
    """Read one stored leaderboard and the time it was last written.

    Args:
        tournament_id: SportsData tournament id.

    Returns:
        Tuple of ``(rows ordered by Position, last-updated row)``. The stamp
        is trimmed to whole seconds.

    Raises:
        IndexError: The tournament row does not exist.
    """
    with db_connection() as connection:
        leaderboard = connection.execute(
            'SELECT * FROM leaderboards WHERE TournamentID == ? ORDER BY Position',
            (tournament_id,),
        ).fetchall()
        last_updated = connection.execute(
            'SELECT strftime("%Y-%m-%d %H:%M:%S", "LeaderboardLastUpdated") as LeaderboardLastUpdated '
            'FROM tournaments WHERE TournamentID == ?',
            (tournament_id,),
        ).fetchall()[0]
    return leaderboard, last_updated


def create_picks_table():
    """Drop and recreate the picks table.

    Text columns on the leaderboard are left as they are. Changing them would
    orphan the database file that already ships with the app.
    """
    with db_connection() as connection:
        connection.execute('DROP TABLE IF EXISTS picks;')
        connection.execute('''
            CREATE TABLE picks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                Owner TEXT NOT NULL,
                TournamentID INTEGER NOT NULL,
                PlayerID INTEGER NOT NULL,
                OneAndDone INTEGER NOT NULL
            );
        ''')
        _ensure_indexes(connection)
        connection.commit()


def add_pick(owner, tournament_id, player_name, one_and_done=False, player_profiles=None):
    """Insert one owner pick resolved from a DraftKings name.

    Args:
        owner: Pool owner name.
        tournament_id: SportsData tournament id.
        player_name: ``DraftKingsName`` to resolve.
        one_and_done: Store 1 when this pick uses the short points table.
        player_profiles: Optional already-loaded profiles. Loaded from disk
            when omitted.
    """
    if player_profiles is None:
        player_profiles = load_player_profiles()
    player_id = get_player_id_from_name(player_name, player_profiles)
    if player_id is None:
        print('No player ID for {}. Cannot add to picks.'.format(player_name))
        return

    with db_connection() as connection:
        connection.execute(
            'INSERT INTO picks (Owner, TournamentID, PlayerID, OneAndDone) VALUES (?, ?, ?, ?)',
            (owner, tournament_id, player_id, one_and_done),
        )
        connection.commit()


def add_picks():
    """Insert ``PICKS`` for ``TOURNAMENT_ID``.

    ``update_picks`` drops the table first. One-and-done names in
    ``ONE_N_DONES`` are not inserted.
    """
    # Resolve every name against one in-memory copy of the profile file.
    player_profiles = load_player_profiles()
    for owner in OWNERS:
        for pick in PICKS[owner]:
            add_pick(owner, TOURNAMENT_ID, pick, player_profiles=player_profiles)


def get_picks(tournament_id):
    """Return each owner's picks for one tournament, in insert order.

    Args:
        tournament_id: SportsData tournament id.

    Returns:
        Dict keyed by owner. Missing owners map to an empty list.
    """
    picks = {}
    with db_connection() as connection:
        for owner in OWNERS:
            picks[owner] = connection.execute(
                'SELECT * FROM picks WHERE Owner == ? and TournamentID == ?',
                (owner, tournament_id),
            ).fetchall()
    return picks


def get_last_updated_str(last_updated):
    """Describe how long ago the leaderboard was written.

    Args:
        last_updated: Row with ``LeaderboardLastUpdated`` as
            ``YYYY-MM-DD HH:MM:SS``.

    Returns:
        Tuple of ``(display text, total seconds)``. The text drops hour or
        minute fields when they are zero.
    """
    delta_time = datetime.now() - datetime.fromisoformat(last_updated['LeaderboardLastUpdated'])
    hours, remainder = divmod(delta_time.total_seconds(), 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours == 0 and minutes == 0:
        text = 'Updated {}s ago'.format(int(seconds))
    elif hours == 0:
        text = 'Updated {}m {}s ago'.format(int(minutes), int(seconds))
    else:
        text = 'Updated {}h {}m {}s ago'.format(int(hours), int(minutes), int(seconds))
    return text, delta_time.total_seconds()


def get_seconds_since_tee_time(tee_time):
    """Seconds from ``tee_time`` until now.

    Args:
        tee_time: A datetime. Future tee times return a negative number.

    Returns:
        Float seconds.
    """
    return (datetime.now() - tee_time).total_seconds()


def annotate_leaderboard(leaderboard):
    """Copy leaderboard rows and add the tee-time fields the results page shows.

    SportsData tee times are Eastern and are shifted three hours earlier for
    Pacific display. The feed never sends ``F``. A golfer whose tee time was
    more than an hour ago and who has no holes-through value is shown as
    finished.

    Args:
        leaderboard: sqlite rows or mappings.

    Returns:
        List of plain dicts in the same order.
    """
    annotated = []
    for row in leaderboard:
        player = dict(row)
        tee_time = player['TeeTime']
        if tee_time is not None and tee_time != 'None':
            # convert_tee_time shifts any datetime it receives, so the original
            # string has to be converted once and then reused.
            converted = convert_tee_time(tee_time)
            player['SecondsSinceTeeTime'] = get_seconds_since_tee_time(converted)
            player['TeeTime'] = get_time_str(converted)
            through = player['TotalThrough']
            if (through is None or through == 'None') and player['SecondsSinceTeeTime'] > 3600:
                player['TotalThrough'] = 'F'
        annotated.append(player)
    return annotated


def index_standings(leaderboard):
    """Map integer player id to the first leaderboard row with that id.

    Args:
        leaderboard: Annotated leaderboard rows.

    Returns:
        Dict used for pick lookups.
    """
    standings = {}
    for player in leaderboard:
        standings.setdefault(int(player['PlayerID']), player)
    return standings


def get_player_standing(player_id, leaderboard):
    """Return the leaderboard row for ``player_id``.

    Args:
        player_id: SportsData id. Numeric strings and ints match.
        leaderboard: A list of rows, or the dict from ``index_standings``.

    Returns:
        The first matching row, or None.
    """
    if isinstance(leaderboard, dict):
        return leaderboard.get(int(player_id))
    for player in leaderboard:
        if int(player_id) == int(player['PlayerID']):
            return player
    return None


def _headshot_urls(headshots):
    """Map player id to the first preferred headshot URL.

    Args:
        headshots: Headshot mappings.

    Returns:
        Dict of ``PlayerID`` to URL. A stored null URL is kept.
    """
    urls = {}
    for headshot in headshots:
        urls.setdefault(headshot['PlayerID'], headshot['PreferredHostedHeadshotUrl'])
    return urls


def _pick_view(profile, standing, pick, photo_url):
    """Build one results-table row for an owner pick.

    Args:
        profile: Player profile.
        standing: Annotated leaderboard row.
        pick: Pick row.
        photo_url: Headshot or profile photo.

    Returns:
        Template mapping.
    """
    return {
        'DraftKingsName': profile['DraftKingsName'],
        'Rank': standing['Rank'],
        'Points': standing['Points'],
        'OneAndDonePoints': standing['OneAndDonePoints'],
        'PhotoUrl': photo_url,
        'OneAndDone': pick['OneAndDone'],
        'TotalThrough': standing['TotalThrough'],
        'TeeTime': standing['TeeTime'],
        'SecondsSinceTeeTime': standing['SecondsSinceTeeTime'],
    }


@app.route('/')
def index():
    """Render the home page.

    Returns:
        HTML response.
    """
    return render_template('index.html')


@app.route('/results')
def results():
    """Render live pool standings for ``TOURNAMENT_ID``.

    Returns:
        HTML response, or a 404 tuple when that tournament is not in SQLite.
    """
    tournament = get_tournament_from_id(TOURNAMENT_ID)
    if tournament is None:
        return 'Tournament not found', 404

    leaderboard, last_updated = get_leaderboard(TOURNAMENT_ID)
    last_updated_str, total_seconds = get_last_updated_str(last_updated)
    leaderboard = annotate_leaderboard(leaderboard)
    standings = index_standings(leaderboard)
    player_profiles = load_player_profiles()
    headshot_urls = _headshot_urls(load_headshots())
    picks = get_picks(TOURNAMENT_ID)

    edited_picks = {}
    totals = {}
    for owner in OWNERS:
        edited_picks[owner] = []
        totals[owner] = 0
        for pick in picks[owner]:
            profile = get_player_profile(player_id=pick['PlayerID'], player_profiles=player_profiles)
            # Natalie is not in the SportsData feed. She scores nothing and
            # uses a picture shipped under static/ when that file is present.
            if profile['DraftKingsName'] == 'Natalie Shelton':
                totals[owner] += 0
                edited_picks[owner].append({
                    'DraftKingsName': profile['DraftKingsName'],
                    'Rank': None,
                    'Points': 0,
                    'OneAndDonePoints': 0,
                    'PhotoUrl': '/static/natalie.jpg',
                    'OneAndDone': pick['OneAndDone'],
                    'TotalThrough': 'None',
                    'TeeTime': 'None',
                    'SecondsSinceTeeTime': 'None',
                })
                continue

            standing = standings.get(int(pick['PlayerID']))
            if standing is None:
                print('Failed to find {} ({}) in leaderboard'.format(profile['DraftKingsName'], pick['PlayerID']))
                continue

            if pick['OneAndDone']:
                totals[owner] += int(standing['OneAndDonePoints'])
            else:
                totals[owner] += int(standing['Points'])

            photo_url = headshot_urls.get(pick['PlayerID'], profile['PhotoUrl'])
            edited_picks[owner].append(_pick_view(profile, standing, pick, photo_url))

    # Higher scores first. sorted() is stable, so a tie stays in OWNERS order.
    totals = dict(sorted(totals.items(), key=lambda item: item[1], reverse=True))
    return render_template(
        'results.html',
        leaderboard=leaderboard,
        picks=edited_picks,
        totals=totals,
        owners=OWNERS,
        last_updated=last_updated_str,
        total_seconds=total_seconds,
        tournament=tournament,
    )


@app.route('/tournaments')
def tournaments():
    """Render active, upcoming, and past tournaments.

    Returns:
        HTML response.
    """
    active_tournaments, upcoming_tournaments, past_tournaments, _relevant = get_tournaments()
    return render_template(
        'tournaments.html',
        active_tournaments=active_tournaments,
        upcoming_tournaments=upcoming_tournaments,
        past_tournaments=past_tournaments,
    )


def convert_tee_time(tee_time):
    """Shift an Eastern tee time three hours earlier for Pacific display.

    Args:
        tee_time: ISO string, datetime, the sentinel ``"None"``, or None.

    Returns:
        A datetime for a real timestamp. ``None`` and ``"None"`` are returned
        unchanged. Passing the returned datetime through again shifts it
        another three hours.
    """
    if type(tee_time) is datetime:
        return tee_time - timedelta(hours=3)
    if type(tee_time) is str and tee_time != 'None':
        return datetime.fromisoformat(tee_time) - timedelta(hours=3)
    return tee_time


def get_time_str(value):
    """Format a tee time as ``h:mmAM`` or ``h:mmPM`` with no leading zero.

    Args:
        value: datetime, ISO string, ``"None"``, or None. Strings are not
            shifted; call ``convert_tee_time`` first when the source is Eastern.

    Returns:
        Display text, or ``"None"`` when there is no clock time.
    """
    if type(value) is datetime:
        return value.strftime('%-I:%M%p')
    if value is not None and value != 'None':
        return datetime.fromisoformat(value).strftime('%-I:%M%p')
    return 'None'


def _extreme_tee_time(leaderboard, round_num, earliest):
    """Find the first or last tee time in a round.

    Args:
        leaderboard: Raw API leaderboard, whose players carry ``Rounds``.
        round_num: 1-based round number.
        earliest: True for the first tee time, False for the last.

    Returns:
        A Pacific datetime, or None when that round has no posted times.
    """
    extreme = None
    for player in leaderboard['Players']:
        rounds = player['Rounds']
        if len(rounds) < round_num:
            continue
        tee_time = convert_tee_time(rounds[round_num - 1]['TeeTime'])
        if tee_time is None:
            continue
        if extreme is None or (tee_time < extreme if earliest else tee_time > extreme):
            extreme = tee_time
    return extreme


def get_first_tee_time(leaderboard, round_num):
    """Return the earliest Pacific tee time for ``round_num``, or None.

    Args:
        leaderboard: Raw API leaderboard.
        round_num: 1-based round number.

    Returns:
        datetime or None.
    """
    return _extreme_tee_time(leaderboard, round_num, earliest=True)


def get_last_tee_time(leaderboard, round_num):
    """Return the latest Pacific tee time for ``round_num``, or None.

    Args:
        leaderboard: Raw API leaderboard.
        round_num: 1-based round number.

    Returns:
        datetime or None.
    """
    return _extreme_tee_time(leaderboard, round_num, earliest=False)


def manage_leaderboard(tournament_id, starting_round_num=1):
    """Poll the leaderboard from one round through the end of the event.

    Sleeps until the first tee time, then refreshes every
    ``LEADERBOARD_UPDATE_PERIOD`` seconds. After the last tee time has passed
    and no golfer still has a ``TotalThrough`` value, the round is over and
    the loop sleeps ``ROUND_END_SLEEP_PERIOD`` before the next round.

    A non-null ``TotalThrough`` means the golfer is still on the course. The
    feed clears that field instead of sending ``F`` when the round ends.

    Profiles are downloaded once at the start. Headshots are not: that
    endpoint rejected a second pull after one successful fetch, so
    ``headshots.json`` stays a saved snapshot. Picks are rebuilt only when
    this run starts at round 1, and only once the first tee time arrives.

    Args:
        tournament_id: SportsData tournament id.
        starting_round_num: 1-based round to begin with.
    """
    round_num = starting_round_num
    first_iteration = True
    fetch_player_profiles()
    leaderboard = api_get_leaderboard(tournament_id)
    num_rounds = len(leaderboard['Tournament']['Rounds'])

    while round_num <= num_rounds:
        if not first_iteration:
            leaderboard = api_get_leaderboard(tournament_id)
        update_leaderboard(tournament_id, leaderboard)
        wait_for_round_start(
            leaderboard,
            round_num,
            do_update_picks=first_iteration and starting_round_num == 1,
        )

        round_complete = True
        last_tee_time = get_last_tee_time(leaderboard, round_num)
        now = datetime.now()
        if last_tee_time is not None and last_tee_time > now:
            print('Now: {}, Last Tee Time: {}. Last tee time not reached.'.format(
                now.strftime('%Y-%m-%d %H:%M:%S'),
                last_tee_time,
            ))
            round_complete = False
        else:
            players_remaining = sum(
                1 for player in leaderboard['Players'] if player['TotalThrough'] is not None
            )
            if players_remaining > 0:
                print('Waiting for {} players to complete round.'.format(players_remaining))
                round_complete = False

        if round_complete:
            print('Round {} is over.'.format(round_num))
            round_num += 1
            print('Sleeping for {} seconds'.format(ROUND_END_SLEEP_PERIOD))
            time.sleep(ROUND_END_SLEEP_PERIOD)
        else:
            print('Sleeping for {} seconds'.format(LEADERBOARD_UPDATE_PERIOD))
            time.sleep(LEADERBOARD_UPDATE_PERIOD)

        first_iteration = False


def wait_for_round_start(leaderboard, round_num, do_update_picks):
    """Block until ``round_num`` tees off, then optionally rebuild picks.

    Args:
        leaderboard: Raw API leaderboard.
        round_num: 1-based round number.
        do_update_picks: When True, replace picks after the wait. This is how
            round 1 locks the hand-entered lineups once tee times are real.
    """
    first_tee_time = get_first_tee_time(leaderboard, round_num)
    if first_tee_time is None:
        print('Tee times are not posted for round {}!'.format(round_num))
        return

    now = datetime.now()
    if now < first_tee_time:
        sleep_seconds = int((first_tee_time - now).total_seconds())
        print('Now: {}, First Tee Time: {}. Sleeping for {} seconds...'.format(
            now.strftime('%Y-%m-%d %H:%M:%S'),
            first_tee_time,
            sleep_seconds,
        ))
        time.sleep(sleep_seconds)

    # Picks are locked in only after a round actually has tee times. A round
    # with an empty tee sheet used to skip this, and still does.
    if do_update_picks:
        update_picks()


def update_picks():
    """Drop the picks table and insert the lineups in ``PICKS``."""
    print('Updating picks...')
    create_picks_table()
    add_picks()


def get_players(tournament_id):
    """Build salary-cap candidates from stored salaries and projections.

    Args:
        tournament_id: SportsData tournament id.

    Returns:
        List of mappings with name, salary, fantasy points, and value.
        Value is projected points per million dollars of salary. Golfers
        without a salary are omitted.
    """
    profiles = _profile_indexes(load_player_profiles())['by_player_id']
    players = []
    for salary in get_salaries(tournament_id):
        if salary['DraftKingsSalary'] is None:
            continue
        # A missing profile still raises TypeError on the subscript below.
        profile = profiles.get(salary['PlayerID'])
        fantasy_points = salary['FantasyPoints']
        draft_salary = salary['DraftKingsSalary']
        players.append({
            'DraftKingsName': profile['DraftKingsName'],
            'DraftKingsSalary': draft_salary,
            'FantasyPoints': fantasy_points,
            'Value': 1e6 * (float(fantasy_points) / float(draft_salary)),
        })
    return players


def get_starting_roster(players, attempts=1000000):
    """Sample random legal lineups and keep the highest projected score.

    Args:
        players: Candidates from ``get_players``.
        attempts: How many random ``NUM_PICKS`` lineups to try. The command
            line uses one million, which is the historical search size.

    Returns:
        The best lineup found, as the original player dicts, or None when
        every sample was over ``MAX_SALARY``.
    """
    max_fantasy_points = 0
    max_players = None
    for i in range(attempts):
        sys.stdout.write('{}\r'.format(i))
        sys.stdout.flush()

        selected_players = random.sample(players, NUM_PICKS)
        total_fantasy_points = sum(player['FantasyPoints'] for player in selected_players)
        total_salary = sum(player['DraftKingsSalary'] for player in selected_players)
        if total_salary <= MAX_SALARY and total_fantasy_points > max_fantasy_points:
            max_fantasy_points = total_fantasy_points
            max_players = selected_players
            print('\nTotal Salary: {:5}, Fantasy Points: {:0.3f}, Players: {}'.format(
                total_salary,
                total_fantasy_points,
                ', '.join(player['DraftKingsName'] for player in selected_players),
            ))
    return max_players


def get_roster(players):
    """Improve a random lineup by swapping in better value at the same salary.

    Each starter is compared with other golfers who cost the same. A golfer
    already chosen, or the starter themself, is not a prospect. The swap
    happens only when the best prospect's value is strictly higher.

    Args:
        players: Candidates from ``get_players``.

    Returns:
        ``Roster`` for the upgraded lineup.
    """
    starting_roster = get_starting_roster(players)

    print()
    print()
    print('Starting Roster')
    for player in starting_roster:
        print('{:30}, Salary: {:5}, Value: {:.3f}'.format(
            player['DraftKingsName'],
            player['DraftKingsSalary'],
            player['Value'],
        ))
    print('Points: {:.3f}'.format(sum(player['FantasyPoints'] for player in starting_roster)))
    print('Salary: {:5}'.format(sum(player['DraftKingsSalary'] for player in starting_roster)))
    print()

    by_salary = {}
    for prospect in players:
        by_salary.setdefault(prospect['DraftKingsSalary'], []).append(prospect)

    final_roster = []
    for player in starting_roster:
        print('{:30}, Salary: {:5}, Value: {:.3f}'.format(
            player['DraftKingsName'],
            player['DraftKingsSalary'],
            player['Value'],
        ))
        taken_names = {chosen['DraftKingsName'] for chosen in final_roster}
        prospects = [
            prospect
            for prospect in by_salary.get(player['DraftKingsSalary'], [])
            if prospect['DraftKingsName'] != player['DraftKingsName']
            and prospect['DraftKingsName'] not in taken_names
        ]
        prospects.sort(key=lambda prospect: prospect['Value'], reverse=True)
        for prospect in prospects:
            print('    Prospect: {}, Salary: {:5}, Value: {:.3f}'.format(
                prospect['DraftKingsName'],
                prospect['DraftKingsSalary'],
                prospect['Value'],
            ))

        if prospects and prospects[0]['Value'] > player['Value']:
            final_roster.append(prospects[0])
        else:
            final_roster.append(player)

    print()
    print('Final Roster')
    for player in final_roster:
        print('{:30}, Salary: {:5}, Value: {:.3f}'.format(
            player['DraftKingsName'],
            player['DraftKingsSalary'],
            player['Value'],
        ))
    print('Total Points: {:.3f}'.format(sum(player['FantasyPoints'] for player in final_roster)))
    print('Total Salary: {:5}'.format(sum(player['DraftKingsSalary'] for player in final_roster)))
    return Roster(final_roster)


def autopick(tournament_id, num_rosters):
    """Search ``num_rosters`` lineups and print them best-projected first.

    Args:
        tournament_id: SportsData tournament id.
        num_rosters: How many independent searches to run.
    """
    players = get_players(tournament_id)
    rosters = [get_roster(players) for _ in range(num_rosters)]
    rosters.sort(key=lambda roster: roster.total_points, reverse=True)

    print()
    print('*********************')
    print('*      ROSTERS      *')
    print('*********************')
    print()
    for roster in rosters:
        print(roster)


def _print_player_table(players):
    """Print the salary table shared by ``values`` and ``points``.

    Args:
        players: Already sorted candidate mappings.
    """
    table = PrettyTable()
    table.field_names = ['Player', 'FantasyPoints', 'Salary', 'Value']
    for player in players:
        table.add_row([
            player['DraftKingsName'],
            player['FantasyPoints'],
            player['DraftKingsSalary'],
            '{:.3f}'.format(player['Value']),
        ])
    print(table)


def values(tournament_id):
    """Print golfers sorted by points per million dollars of salary.

    Args:
        tournament_id: SportsData tournament id.
    """
    players = sorted(get_players(tournament_id), key=lambda player: player['Value'], reverse=True)
    _print_player_table(players)


def points(tournament_id):
    """Print golfers sorted by projected fantasy points.

    Args:
        tournament_id: SportsData tournament id.
    """
    players = sorted(get_players(tournament_id), key=lambda player: player['FantasyPoints'], reverse=True)
    _print_player_table(players)


def sandbox():
    """Print the headshot feed. This command calls the network."""
    pprint(api_get_headshots())


def main():
    """Dispatch ``sys.argv`` to one command."""
    args = parse_args()
    command = args.cmd

    if command == 'players':
        fetch_player_profiles()
    elif command == 'create-leaderboard-table':
        create_leaderboard_table()
    elif command == 'manage-leaderboard':
        manage_leaderboard(TOURNAMENT_ID, args.round_num)
    elif command == 'update-leaderboard':
        update_leaderboard(TOURNAMENT_ID)
    elif command == 'tournaments':
        create_tournaments_table()
        populate_tournaments_table()
    elif command == 'salaries':
        create_salaries_table()
        populate_salaries_table(TOURNAMENT_ID)
    elif command == 'autopick':
        autopick(TOURNAMENT_ID, args.num_rosters)
    elif command == 'values':
        values(TOURNAMENT_ID)
    elif command == 'points':
        points(TOURNAMENT_ID)
    elif command == 'picks':
        update_picks()
    elif command == 'clear-picks':
        create_picks_table()
        update_leaderboard(TOURNAMENT_ID)
    elif command == 'flask':
        app.run(host='0.0.0.0', port=80, debug=True)
    elif command == 'sandbox':
        sandbox()


if __name__ == '__main__':
    main()
