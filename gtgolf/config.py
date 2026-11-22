"""Week settings, scoring tables, and file paths.

Edit this module to change the tournament, the five lineups, or the
SportsData.io key. The command line and the website read these names at
call time, so a running process picks up edits on the next command.
"""

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
# Overridden in tests. The CLI and the website use the file in the working directory.
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
