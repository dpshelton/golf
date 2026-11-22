"""SQLite schema and queries for tournaments, salaries, leaderboards, and picks.

``config.DATABASE`` is read when a connection opens, so tests can point the
process at a copy of the file.
"""

import sqlite3
from contextlib import contextmanager
from datetime import datetime

from gtgolf import api, config, profiles, scoring


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
    connection = sqlite3.connect(config.DATABASE)
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
    tournaments = api.api_get_all_tournaments()
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

    by_id = profiles._profile_indexes(profiles.load_player_profiles())['by_player_id']
    fantasy_points = {}
    for projection in api.api_get_projections(tournament_id):
        fantasy_points[projection['PlayerID']] = projection['FantasyPoints']

    rows = []
    for dfs_slate in api.api_get_dfs_slates(tournament_id):
        if dfs_slate['Operator'] != 'DraftKings':
            continue
        for player in dfs_slate['DfsSlatePlayers']:
            profile = by_id.get(player['PlayerID'])
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
        leaderboard = api.api_get_leaderboard(tournament_id)
    parsed = scoring.parse_leaderboard(leaderboard, profiles.load_player_profiles())

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
        player_profiles = profiles.load_player_profiles()
    player_id = profiles.get_player_id_from_name(player_name, player_profiles)
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
    player_profiles = profiles.load_player_profiles()
    for owner in config.OWNERS:
        for pick in config.PICKS[owner]:
            add_pick(owner, config.TOURNAMENT_ID, pick, player_profiles=player_profiles)


def get_picks(tournament_id):
    """Return each owner's picks for one tournament, in insert order.

    Args:
        tournament_id: SportsData tournament id.

    Returns:
        Dict keyed by owner. Missing owners map to an empty list.
    """
    picks = {}
    with db_connection() as connection:
        for owner in config.OWNERS:
            picks[owner] = connection.execute(
                'SELECT * FROM picks WHERE Owner == ? and TournamentID == ?',
                (owner, tournament_id),
            ).fetchall()
    return picks
