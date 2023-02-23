#!/usr/bin/env python3

import sys
import argparse
import requests
import json
from pprint import pprint
from datetime import datetime, timedelta
import time
import inspect
from prettytable import PrettyTable
import sqlite3
from flask import Flask, escape, request, render_template
from draft_kings import Sport, Client
import random

TOURNAMENT_ID   = 533
MAJOR           = False

MAX_SALARY      = 50000
NUM_PICKS       = 6

PICKS = {
    'Ben': [
        'Rory McIlroy',
        'Max Homa',
        'Will Zalatoris',
        'Corey Conners',
        'Tom Hoge',
        'Doug Ghim',
    ],
    'Greg': [
        'Justin Thomas',
        'Tony Finau',
        'Jordan Spieth',
        'Tyrrell Hatton',
        'Adam Hadwin',
        'Kevin Tway',
    ],
    'Mike': [
        'Justin Thomas',
        'Patrick Cantlay',
        'Will Zalatoris',
        'Wyndham Clark',
        'Tommy Fleetwood',
        'Patrick Rodgers',
    ],
    'Don': [
        'Jon Rahm',
        'Collin Morikawa',
        'Jason Day',
        'Tommy Fleetwood',
        'Tiger Woods',
        'Kevin Kisner',
    ],
    'Sean': [
        'Scottie Scheffler',
        'Justin Thomas',
        'Jordan Spieth',
        'Billy Horschel',
        'Nick Taylor',
        'J.B. Holmes',
    ],
}

ONE_N_DONES = {
    'Ben' : '',
    'Greg': '',
    'Mike': '',
    'Don' : '',
    'Sean': '',
}

KEY = 'a478d29a98e54eac8e9ebf1f218dd0b8'

START_DAY_WINDOW            = 4
END_DAY_WINDOW              = 1
PLAYERS_FILENAME            = 'player_profiles.json'
LEADERBOARD_UPDATE_PERIOD   = 10 * 60
ROUND_END_SLEEP_PERIOD      = 6 * 60 * 60
MAJOR_MULTIPLIER            = 1.5

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

POINTS = [
    (1 , 1   , 150),
    (2 , 2   , 75 ),
    (3 , 3   , 50 ),
    (4 , 4   , 35 ),
    (5 , 5   , 30 ),
    (6 , 6   , 25 ),
    (7 , 7   , 20 ),
    (8 , 8   , 18 ),
    (9 , 9   , 16 ),
    (10, 10  , 14 ),
    (11, 15  , 12 ),
    (16, 20  , 10 ),
    (21, 25  , 8  ),
    (26, 30  , 7  ),
    (31, 40  , 6  ),
    (41, 50  , 5  ),
    (51, 60  , 4  ),
    (61, 1000, 3  ),
]

ONE_N_DONE_POINTS = [
    (1 , 1   , 50),
    (2 , 2   , 25),
    (3 , 3   , 15),
    (4 , 4   , 12),
    (5 , 5   , 10),
    (6 , 6   , 8 ),
    (7 , 7   , 6 ),
    (8 , 8   , 5 ),
    (9 , 9   , 4 ),
    (10, 10  , 3 ),
]

OWNERS = [
    'Ben',
    'Greg',
    'Mike',
    'Don',
    'Sean',
]

BASE_URL = 'https://fly.sportsdata.io'

app = Flask(__name__)

class Roster():
    def __init__(self, players):
        self.players = sorted(players, key=lambda x: x['DraftKingsSalary'], reverse=True)
        self.total_points = self.get_total_points()
        self.total_salary = self.get_total_salary()

    def get_total_points(self):
        return sum([player['FantasyPoints'] for player in self.players])

    def get_total_salary(self):
        return sum([player['DraftKingsSalary'] for player in self.players])

    def __str__(self):
        string = ''
        string += 'Points: {:.3f}, Salary: {:5}\n'.format(self.total_points, self.total_salary)
        for player in self.players:
            string += '    {:30}, Points: {:.3f}, Salary: {:5}, Value: {:.3f}\n'.format(
                player['DraftKingsName'],
                player['FantasyPoints'],
                player['DraftKingsSalary'],
                player['Value'],
            )
        return string

def parse_args():
    description = 'Fantasy Golf Tool'

    parser = argparse.ArgumentParser(description=description, formatter_class=argparse.RawTextHelpFormatter)

    parser.add_argument('cmd', help='Directory path', type=str, choices=CMDS)
    parser.add_argument('-r', '--round-num', help='Round number', type=int, default=1)
    parser.add_argument('-n', '--num-rosters', help='Number of rosters', type=int, default=1)

    return parser.parse_args()

def api_request(url):
    payload = {
        'key': KEY,
    }

    r = requests.get(url, params=payload)
    return json.loads(r.text)

def api_get_all_players():
    print('API-CALL: {}'.format(inspect.currentframe().f_code.co_name))
    print('{}'.format(BASE_URL + '/golf/v2/json/Players'))
    return api_request(BASE_URL + '/golf/v2/json/Players')

def api_get_all_tournaments():
    print('API-CALL: {}'.format(inspect.currentframe().f_code.co_name))
    return api_request(BASE_URL + '/golf/v2/json/Tournaments')

def api_get_leaderboard(tournament_id):
    print('API-CALL: {}'.format(inspect.currentframe().f_code.co_name))
    return api_request(BASE_URL + '/golf/v2/json/Leaderboard/{}'.format(tournament_id))

def api_get_projections(tournament_id):
    print('API-CALL: {}'.format(inspect.currentframe().f_code.co_name))
    return api_request(BASE_URL + '/golf/v2/json/PlayerTournamentProjectionStats/{}'.format(tournament_id))

def api_get_dfs_slates(tournament_id):
    print('API-CALL: {}'.format(inspect.currentframe().f_code.co_name))
    return api_request(BASE_URL + '/golf/v2/json/DfsSlatesByTournament/{}'.format(tournament_id))

def get_active_tournaments():
    active_tournaments = []

    tournaments = api_get_all_tournaments()
    for tournament in tournaments:
        if tournament['IsInProgress']:
            active_tournaments.append(tournament)

    return active_tournaments

def get_next_tournament():
    tournaments = api_get_all_tournaments()

    today = datetime.today()

    for tournament in tournaments:
        start_date = datetime.fromisoformat(tournament['StartDate'])
        end_date = datetime.fromisoformat(tournament['EndDate'])

        if today >= start_date - timedelta(days=START_DAY_WINDOW) and today < end_date + timedelta(days=END_DAY_WINDOW):
            pprint(tournament)

    return tournaments

def get_player_profile(player_id=None, draft_kings_player_id=None, player_profiles=None):
    for player_profile in player_profiles:
        if player_id is not None:
            if player_id == player_profile['PlayerID']:
                return player_profile

        if draft_kings_player_id is not None:
            if draft_kings_player_id == player_profile['DraftKingsPlayerID']:
                return player_profile

    return None

def get_player_id_from_name(player_name, player_profiles):
    for player_profile in player_profiles:
        if player_name == player_profile['DraftKingsName']:
            return player_profile['PlayerID']

    return None

def get_points(rank, one_n_done=False, major=False):
    multiplier = MAJOR_MULTIPLIER if major else 1

    if rank is None:
        return 0
    else:
        if one_n_done:
            for start, end, points in ONE_N_DONE_POINTS:
                if rank >= start and rank <= end:
                    return points * multiplier
        else:
            for start, end, points in POINTS:
                if rank >= start and rank <= end:
                    return points * multiplier

    return 0

def parse_leaderboard(leaderboard, player_profiles):
    # Unscramble the 'Rank' from fantasydata.com
    ranked_leaderboard = []
    unranked_leaderboard = []
    rank = None
    # Assigning rank starting at 1 (instead of 0)

    ranked_player_count = 0
    prev_total_score = None
    current_rank = 1

    for i, player in enumerate(leaderboard['Players']):
        player_profile = get_player_profile(player_id=player['PlayerID'], player_profiles=player_profiles)

        if player['TotalScore'] is not None:
            ranked_player_count += 1

            if player['TotalScore'] != prev_total_score:
                current_rank = ranked_player_count

            rank = current_rank
            prev_total_score = player['TotalScore']

            ranked_leaderboard.append({
                'PlayerID'          : player['PlayerID'],
                'Rank'              : str(rank),
                'DraftKingsPlayerID': player_profile['DraftKingsPlayerID'],
                'DraftKingsName'    : player_profile['DraftKingsName'],
                'Points'            : str(get_points(rank, one_n_done=False, major=MAJOR)),
                'OneAndDonePoints'  : str(get_points(rank, one_n_done=True , major=MAJOR)),
            })
        else:
            rank = None

            unranked_leaderboard.append({
                'PlayerID'          : player['PlayerID'],
                'Rank'              : str(rank),
                'DraftKingsPlayerID': player_profile['DraftKingsPlayerID'],
                'DraftKingsName'    : player_profile['DraftKingsName'],
                'Points'            : str(get_points(rank, one_n_done=False, major=MAJOR)),
                'OneAndDonePoints'  : str(get_points(rank, one_n_done=True , major=MAJOR)),
            })

    return ranked_leaderboard + unranked_leaderboard

def fetch_player_profiles():
    player_profiles = api_get_all_players()

    output_file = open(PLAYERS_FILENAME, 'w')
    json.dump(player_profiles, output_file)
    output_file.close()

    return player_profiles

def load_player_profiles():
    input_file = open(PLAYERS_FILENAME, 'r')
    player_profiles = json.load(input_file)

    return player_profiles

def get_db_connection():
    conn = sqlite3.connect('database.db')
    conn.row_factory = sqlite3.Row
    return conn

def create_tournaments_table():
    conn = get_db_connection()
    curr = conn.cursor()
    curr.execute('DROP TABLE IF EXISTS tournaments;')
    curr.execute('''
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
    conn.commit()
    conn.close()

def populate_tournaments_table():
    tournaments = api_get_all_tournaments()

    conn = get_db_connection()
    curr = conn.cursor()

    for tournament in tournaments:
        curr.execute('INSERT INTO tournaments (TournamentID, Name, StartDate, EndDate, Location, Venue) VALUES (?, ?, ?, ?, ?, ?)', (
            tournament['TournamentID'],
            tournament['Name'],
            tournament['StartDate'],
            tournament['EndDate'],
            tournament['Location'],
            tournament['Venue'],
        ))

    conn.commit()
    conn.close()

def create_salaries_table():
    conn = get_db_connection()
    curr = conn.cursor()
    curr.execute('DROP TABLE IF EXISTS salaries;')
    curr.execute('''
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
    conn.commit()
    conn.close()

def populate_salaries_table(tournament_id):
    tournament = get_tournament_from_id(tournament_id)
    if tournament is None:
        return

    player_profiles = load_player_profiles()

    fantasy_points = {}
    projections = api_get_projections(TOURNAMENT_ID)
    for projection in projections:
        fantasy_points[projection['PlayerID']] = projection['FantasyPoints']

    dfs_slates = api_get_dfs_slates(TOURNAMENT_ID)
    for dfs_slate in dfs_slates:
        if (dfs_slate['Operator'] == 'DraftKings'):
            conn = get_db_connection()
            curr = conn.cursor()

            for player in dfs_slate['DfsSlatePlayers']:
                player_profile = get_player_profile(player_id=player['PlayerID'], player_profiles=player_profiles)

                if player_profile is not None:
                    curr.execute('INSERT INTO salaries (TournamentID, PlayerID, DraftKingsPlayerID, DraftKingsName, DraftKingsSalary, FantasyPoints) VALUES (?, ?, ?, ?, ?, ?)', (
                        tournament_id,
                        player_profile['PlayerID'],
                        player_profile['DraftKingsPlayerID'],
                        player_profile['DraftKingsName'],
                        player['OperatorSalary'],
                        fantasy_points.get(player_profile['PlayerID'], 0),
                    ))
                else:
                    print('WTF {}'.format(player['OperatorPlayerName']))

            conn.commit()
            conn.close()

            break

# def populate_salaries_table(tournament_id):
#     tournament = get_tournament_from_id(tournament_id)
#     if tournament is None:
#         return

#     player_profiles = load_player_profiles()

#     contests = Client().contests(sport=Sport.GOLF)
#     for draft_group in contests.draft_groups:
#         draft_group_details = Client().draft_group_details(draft_group_id=draft_group.draft_group_id)

#         # print('{}         {}'.format(draft_group_details.games[0].name, tournament['Name']))
#         # if draft_group_details.games[0].name != 'Arnold Palmer Invitational presented by Mastercard':
#         if draft_group_details.games[0].name != tournament['Name']:
#             continue
#         if draft_group_details.leagues[0].abbreviation != 'PGA':
#             continue
#         game_type_rules = Client().game_type_rules(game_type_id=draft_group_details.contest_details.type_id)
#         if not game_type_rules.salary_cap_details.is_enabled or int(game_type_rules.salary_cap_details.maximum_value) != 50000:
#             continue

#         draftables = Client().draftables(draft_group_id=draft_group_details.draft_group_id)

#         conn = get_db_connection()
#         curr = conn.cursor()

#         for player in draftables.players:
#             player_profile = get_player_profile(draft_kings_player_id=player.player_id, player_profiles=player_profiles)

#             if player_profile is not None:
#                 if player.name_details.display != player_profile['DraftKingsName']:
#                     print('Player names do not match {} vs {}'.format(player.name_details.display, player_profile['DraftKingsName']))

#                 curr.execute('INSERT INTO salaries (TournamentID, PlayerID, DraftKingsPlayerID, DraftKingsName, DraftKingsSalary) VALUES (?, ?, ?, ?, ?)', (
#                     tournament_id,
#                     player_profile['PlayerID'],
#                     player_profile['DraftKingsPlayerID'],
#                     player_profile['DraftKingsName'],
#                     player.salary,
#                 ))
#             else:
#                 print('WTF {}'.format(player.name_details.display))

#         conn.commit()
#         conn.close()

#         break

# def populate_salaries_table(tournament_id):
#     # player_profiles = load_player_profiles()

#     # contests = Client().contests(sport=Sport.GOLF)
#     # for draft_group in contests.draft_groups:
#     #     draft_group_details = Client().draft_group_details(draft_group_id=draft_group.draft_group_id)
#     #     if draft_group_details.leagues[0].abbreviation == 'PGA':
#     #         game_type_rules = Client().game_type_rules(game_type_id=draft_group_details.contest_details.type_id)
#     #         if game_type_rules.salary_cap_details.is_enabled and int(game_type_rules.salary_cap_details.maximum_value) == 50000:
#     #             # print(draft_group_details.games[0].name)
#     #             # print(draft_group_details.draft_group_id)
#     #             print(dir(Client().available_players(draft_group_id=draft_group_details.draft_group_id)))

#     #             draftables = Client().draftables(draft_group_id=draft_group_details.draft_group_id)
#     #             for player in draftables.players:
#     #                 player_profile = get_player_profile(draft_kings_player_id=player.player_id, player_profiles=player_profiles)

#     #                 if player_profile is not None:
#     #                     if player.name_details.display != player_profile['DraftKingsName']:
#     #                         print('Player names do not match {} vs {}'.format(player.name_details.display, player_profile['DraftKingsName']))
#     #                     print('{}, {}, {}, {}'.format(player.player_id, player.name_details.display, player_profile['DraftKingsName'], player.salary))
#     #                 else:
#     #                     print('WTF {}'.format(player.name_details.display))

#     if tournament is not None:
#         tournament['Name']

#     salaries = api_get_salaries(tournament_id)
#     player_profiles = load_player_profiles()

#     conn = get_db_connection()
#     curr = conn.cursor()

#     for salary in salaries:
#         player_profile = get_player_profile(player_id=salary['PlayerID'], player_profiles=player_profiles)

#         curr.execute('INSERT INTO salaries (TournamentID, PlayerID, DraftKingsName, DraftKingsSalary) VALUES (?, ?, ?, ?)', (
#             tournament_id,
#             salary['PlayerID'],
#             player_profile['DraftKingsName'],
#             salary['DraftKingsSalary'],
#         ))

#     conn.commit()
#     conn.close()

def get_tournaments():
    conn = get_db_connection()

    active_tournaments = conn.execute('''SELECT
            TournamentID,
            Name,
            strftime("%Y-%m-%d", "StartDate") as StartDate,
            strftime("%Y-%m-%d", "EndDate") as EndDate,
            Location,
            Venue
        FROM tournaments WHERE StartDate <= datetime('now') AND EndDate >= datetime('now')
        ORDER BY StartDate ''').fetchall()

    upcoming_tournaments = conn.execute('''SELECT
            TournamentID,
            Name,
            strftime("%Y-%m-%d", "StartDate") as StartDate,
            strftime("%Y-%m-%d", "EndDate") as EndDate,
            Location,
            Venue
        FROM tournaments WHERE StartDate > datetime('now')
        ORDER BY StartDate ''').fetchall()

    past_tournaments = conn.execute('''SELECT
            TournamentID,
            Name,
            strftime("%Y-%m-%d", "StartDate") as StartDate,
            strftime("%Y-%m-%d", "EndDate") as EndDate,
            Location,
            Venue
        FROM tournaments WHERE EndDate < datetime('now') AND EndDate >= datetime('now', '-1 year')
        ORDER BY EndDate DESC''').fetchall()

    relevant_tournaments = conn.execute('''SELECT
            TournamentID,
            Name,
            strftime("%Y-%m-%d", "StartDate") as StartDate,
            strftime("%Y-%m-%d", "EndDate") as EndDate,
            Location,
            Venue
        FROM tournaments WHERE EndDate >= datetime('now', '-2 days') AND StartDate <= datetime('now', '+21 days')
        ORDER BY EndDate''').fetchall()

    conn.close()

    return active_tournaments, upcoming_tournaments, past_tournaments, relevant_tournaments

def get_tournament_from_id(tournament_id):
    conn = get_db_connection()
    tournaments = conn.execute('SELECT * FROM tournaments WHERE TournamentID == {}'.format(tournament_id)).fetchall()
    conn.close()

    if len(tournaments) >= 0:
        return tournaments[0]
    else:
        return None

def get_salaries(tournament_id):
    conn = get_db_connection()
    salaries = conn.execute('SELECT * FROM salaries WHERE TournamentID == {}'.format(tournament_id)).fetchall()
    conn.close()

    if len(salaries) == 0:
        populate_salaries_table(tournament_id)

        conn = get_db_connection()
        salaries = conn.execute('SELECT * FROM salaries WHERE TournamentID == {}'.format(tournament_id)).fetchall()
        conn.close()

    return salaries

@app.route('/')
def index():
    return render_template('index.html')

def get_player_standing(player_id, leaderboard):
    for player in leaderboard:
        if int(player_id) == int(player['PlayerID']):
            return player

    return None

@app.route('/results')
def results():
    # tournament_id = request.args.get('tournamentid')
    tournament_id = TOURNAMENT_ID  # TODO: switch back to dropdown

    tournament = get_tournament_from_id(tournament_id)
    if tournament is None:
        return

    leaderboard, last_updated = get_leaderboard(tournament_id)

    player_profiles = load_player_profiles()
    picks = get_picks(tournament_id)

    edited_picks = {}
    totals = {}
    for owner in OWNERS:
        edited_picks[owner] = []
        totals[owner] = 0
        for pick in picks[owner]:
            player_profile = get_player_profile(player_id=pick['PlayerID'], player_profiles=player_profiles)

            if player_profile['DraftKingsName'] == 'Natalie Shelton':
                totals[owner] += 0

                edited_picks[owner].append({
                    'DraftKingsName'    : player_profile['DraftKingsName'],
                    'Rank'              : None,
                    'Points'            : 0,
                    'OneAndDonePoints'  : 0,
                    'PhotoUrl'          : '/static/natalie.jpg',
                    'OneAndDone'        : pick['OneAndDone'],
                })
            else:
                standing = get_player_standing(pick['PlayerID'], leaderboard)
                if standing is None:
                    print('Failed to find {} ({}) in leaderboard'.format(player_profile['DraftKingsName'], pick['PlayerID']))
                else:
                    standing['Rank']
                    if pick['OneAndDone']:
                        totals[owner] += float(standing['OneAndDonePoints']) if MAJOR else int(standing['OneAndDonePoints'])
                    else:
                        totals[owner] += float(standing['Points']) if MAJOR else int(standing['Points'])
                    edited_picks[owner].append({
                        'DraftKingsName'    : player_profile['DraftKingsName'],
                        'Rank'              : standing['Rank'],
                        'Points'            : standing['Points'],
                        'OneAndDonePoints'  : standing['OneAndDonePoints'],
                        'PhotoUrl'          : player_profile['PhotoUrl'],
                        'OneAndDone'        : pick['OneAndDone'],
                    })

    totals = dict(sorted(totals.items(), key=lambda item: item[1], reverse=True))

    return render_template('results.html', leaderboard=leaderboard, picks=edited_picks, totals=totals, owners=OWNERS, last_updated=last_updated, tournament=tournament)

@app.route('/tournaments')
def tournaments():
    active_tournaments, upcoming_tournaments, past_tournaments, relevant_tournaments = get_tournaments()

    return render_template('tournaments.html',
        active_tournaments      = active_tournaments,
        upcoming_tournaments    = upcoming_tournaments,
        past_tournaments        = past_tournaments,
    )

# @app.route('/picks')
# def picks():
#     tournament_id = request.args.get('tournamentid')

#     active_tournaments, upcoming_tournaments, past_tournaments, relevant_tournaments = get_tournaments()

#     selected_tournament = None
#     if tournament_id is not None:
#         for tournament in relevant_tournaments:
#             if int(tournament_id) == int(tournament['TournamentID']):
#                 selected_tournament = tournament
#                 break

#     if selected_tournament is None:
#         selected_string = 'Select a tournament'
#         salaries = []
#     else:
#         selected_string = '{} - {}'.format(tournament['Name'], tournament['StartDate'])
#         salaries = get_salaries(selected_tournament['TournamentID'])
#         player_profiles = load_player_profiles()

#     players = []
#     for salary in salaries:
#         player_profile = get_player_profile(player_id=salary['PlayerID'], player_profiles=player_profiles)

#         if salary['DraftKingsSalary'] is not None:
#             players.append({
#                 'DraftKingsName': player_profile['DraftKingsName'],
#                 'DraftKingsSalary': salary['DraftKingsSalary'],
#             })

#     if len(players) > 0:
#         players = sorted(players, key=lambda x: x['DraftKingsSalary'], reverse=True)

#     return render_template('picks.html', players=players, tournaments=relevant_tournaments, tournamentid=tournament_id, selected_string=selected_string)

def create_leaderboard_table():
    conn = get_db_connection()
    curr = conn.cursor()
    curr.execute('DROP TABLE IF EXISTS leaderboards;')
    curr.execute('''
        CREATE TABLE leaderboards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            TournamentID INTEGER NOT NULL,
            PlayerID TEXT NOT NULL,
            Rank TEXT NOT NULL,
            DraftKingsPlayerID TEXT NOT NULL,
            DraftKingsName TEXT NOT NULL,
            Points TEXT NOT NULL,
            OneAndDonePoints TEXT NOT NULL,
            Position INTEGER NOT NULL
        );
    ''')
    conn.commit()
    conn.close()

def update_leaderboard(tournament_id, leaderboard=None):
    if leaderboard is None:
        leaderboard = api_get_leaderboard(tournament_id)
    player_profiles = load_player_profiles()
    parsed_leaderboard = parse_leaderboard(leaderboard, player_profiles)

    conn = get_db_connection()
    curr = conn.cursor()

    for position, player in enumerate(parsed_leaderboard):
        db_player = conn.execute('SELECT id FROM leaderboards WHERE TournamentID == ? AND PlayerID == ?', (
            tournament_id,
            player['PlayerID']
        )).fetchall()
        if len(db_player) == 0:
            curr.execute('INSERT INTO leaderboards (TournamentID, PlayerID, Rank, DraftKingsPlayerID, DraftKingsName, Points, OneAndDonePoints, Position) VALUES (?, ?, ?, ?, ?, ?, ?, ?)', (
                tournament_id,
                player['PlayerID'],
                player['Rank'],
                player['DraftKingsPlayerID'] if player['DraftKingsPlayerID'] is not None else 'Unknown',
                player['DraftKingsName'] if player['DraftKingsName'] is not None else 'Unknown',
                player['Points'],
                player['OneAndDonePoints'],
                position,
            ))
        else:
            curr.execute('UPDATE leaderboards SET Rank=?, Points=?, OneAndDonePoints=?, Position=? WHERE TournamentID==? AND PlayerID==?', (
                player['Rank'],
                player['Points'],
                player['OneAndDonePoints'],
                position,
                tournament_id,
                player['PlayerID'],
            ))

    curr.execute('UPDATE tournaments SET LeaderboardLastUpdated=? WHERE TournamentID=?', (
        datetime.now(),
        tournament_id,
    ))

    conn.commit()
    conn.close()

def get_leaderboard(tournament_id):
    conn = get_db_connection()
    curr = conn.cursor()

    leaderboard = conn.execute('SELECT * FROM leaderboards WHERE TournamentID == ? ORDER BY Position', (
        tournament_id,
    )).fetchall()

    last_updated = conn.execute('SELECT strftime("%Y-%m-%d %H:%M:%S", "LeaderboardLastUpdated") as LeaderboardLastUpdated FROM tournaments WHERE TournamentID == ?', (
        tournament_id,
    )).fetchall()[0]

    conn.commit()
    conn.close()

    return leaderboard, last_updated

def create_picks_table():
    # TODO: convert all appropriate table TEXTs to INTEGERs
    conn = get_db_connection()
    curr = conn.cursor()
    curr.execute('DROP TABLE IF EXISTS picks;')
    curr.execute('''
        CREATE TABLE picks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            Owner TEXT NOT NULL,
            TournamentID INTEGER NOT NULL,
            PlayerID INTEGER NOT NULL,
            OneAndDone INTEGER NOT NULL
        );
    ''')
    conn.commit()
    conn.close()

def add_pick(owner, tournament_id, player_name, one_and_done=False):
    conn = get_db_connection()
    curr = conn.cursor()

    # TODO: load player profiles once
    player_profiles = load_player_profiles()
    player_id = get_player_id_from_name(player_name, player_profiles)

    if player_id is not None:
        curr.execute('INSERT INTO picks (Owner, TournamentID, PlayerID, OneAndDone) VALUES (?, ?, ?, ?)', (owner, tournament_id, player_id, one_and_done))
    else:
        print('No player ID for {}. Cannot add to picks.'.format(player_name))

    conn.commit()
    conn.close()

def add_picks():
    conn = get_db_connection()
    curr = conn.cursor()

    for owner in OWNERS:
        # Add picks
        for pick in PICKS[owner]:
            add_pick(owner, TOURNAMENT_ID, pick)

        # Add One-N-Done
        add_pick(owner, TOURNAMENT_ID, ONE_N_DONES[owner], True)

    conn.commit()
    conn.close()

def get_picks(tournament_id):
    conn = get_db_connection()
    curr = conn.cursor()

    picks = {}
    for owner in OWNERS:
        picks[owner] = conn.execute('SELECT * FROM picks WHERE Owner == ? and TournamentID == ?', (
            owner,
            tournament_id,
        )).fetchall()

    conn.commit()
    conn.close()

    return picks

def convert_tee_time(tee_time):
    if tee_time is not None:
        # Tee times are EST
        tee_time = datetime.fromisoformat(tee_time) - timedelta(hours=3)

    return tee_time

def get_first_tee_time(leaderboard, round_num):
    first_tee_time = None
    for player in leaderboard['Players']:
        if len(player['Rounds']) >= round_num:
            tee_time = convert_tee_time(player['Rounds'][round_num-1]['TeeTime'])
            if tee_time is not None:
                if first_tee_time is None:
                    first_tee_time = tee_time
                elif tee_time < first_tee_time:
                        first_tee_time = tee_time

    return first_tee_time

def get_last_tee_time(leaderboard, round_num):
    last_tee_time = None
    for player in leaderboard['Players']:
        if len(player['Rounds']) >= round_num:
            tee_time = convert_tee_time(player['Rounds'][round_num-1]['TeeTime'])
            if tee_time is not None:
                if last_tee_time is None:
                    last_tee_time = tee_time
                elif tee_time > last_tee_time:
                        last_tee_time = tee_time

    return last_tee_time

def manage_leaderboard(tournament_id, starting_round_num=1):
    round_num = starting_round_num

    first_iteration = True
    leaderboard = api_get_leaderboard(tournament_id)
    num_rounds = len(leaderboard['Tournament']['Rounds'])

    prev_players_remaining = None
    while round_num <= num_rounds:
        if not first_iteration:
            leaderboard = api_get_leaderboard(tournament_id)
        update_leaderboard(tournament_id, leaderboard)

        if (first_iteration and starting_round_num == 1):
            wait_for_round_start(leaderboard, round_num, True)
        else:
            wait_for_round_start(leaderboard, round_num, False)

        round_complete = True
        last_tee_time = get_last_tee_time(leaderboard, round_num)
        now = datetime.now()
        if last_tee_time is not None and last_tee_time > now:
            print('Now: {}, Last Tee Time: {}. Last tee time not reached.'.format(now.strftime("%Y-%m-%d %H:%M:%S"), last_tee_time))
            round_complete = False
        else:
            players_remaining = 0
            for player in leaderboard['Players']:
                if player['TotalThrough'] is not None:
                    players_remaining += 1

            if players_remaining > 0:

                print('Waiting for {} players to complete round.'.format(players_remaining))
                round_complete = False

            prev_players_remaining = players_remaining

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
    first_tee_time = get_first_tee_time(leaderboard, round_num)

    if first_tee_time is None:
        print('Tee times are not posted for round {}!'.format(round_num))
    else:
        now = datetime.now()
        if now < first_tee_time:
            sleep_timedelta = first_tee_time - now
            sleep_seconds = int(sleep_timedelta.total_seconds())
            print('Now: {}, First Tee Time: {}. Sleeping for {} seconds...'.format(now.strftime("%Y-%m-%d %H:%M:%S"), first_tee_time, sleep_seconds))
            time.sleep(sleep_seconds)

        if do_update_picks:
            update_picks()

def update_picks():
    print('Updating picks...')
    create_picks_table()
    add_picks()

def get_players(tournament_id):
    player_profiles = load_player_profiles()

    salaries = get_salaries(tournament_id)

    players = []
    for salary in salaries:
        player_profile = get_player_profile(player_id=salary['PlayerID'], player_profiles=player_profiles)

        if salary['DraftKingsSalary'] is not None:
            player = {
                'DraftKingsName'    : player_profile['DraftKingsName'],
                'DraftKingsSalary'  : salary['DraftKingsSalary'],
                'FantasyPoints'     : salary['FantasyPoints'],
                'Value'             : 1e6 * (float(salary['FantasyPoints']) / float(salary['DraftKingsSalary'])),
            }
            players.append(player)

    return players

def get_starting_roster(players):
    max_fantasy_points = 0
    max_players = None
    for i in range(1000000):
        sys.stdout.write('{}\r'.format(i))
        sys.stdout.flush()

        selected_players = random.sample(players, NUM_PICKS)

        total_fantasy_points = sum([player['FantasyPoints'] for player in selected_players])
        total_salary         = sum([player['DraftKingsSalary'] for player in selected_players])
        if (total_salary <= MAX_SALARY and total_fantasy_points > max_fantasy_points):
            max_fantasy_points  = total_fantasy_points
            max_players         = selected_players
            print('\nTotal Salary: {:5}, Fantasy Points: {:0.3f}, Players: {}'.format(
                total_salary,
                total_fantasy_points,
                ', '.join([player['DraftKingsName'] for player in selected_players])
            ))

    return max_players

def get_roster(players):
    starting_roster = get_starting_roster(players)

    print()
    print()
    print('Starting Roster')
    for player in starting_roster:
        print('{:30}, Salary: {:5}, Value: {:.3f}'.format(player['DraftKingsName'], player['DraftKingsSalary'], player['Value']))
    print('Points: {:.3f}'.format(sum([player['FantasyPoints'] for player in starting_roster])))
    print('Salary: {:5}'.format(sum([player['DraftKingsSalary'] for player in starting_roster])))
    print()

    final_roster = []
    for player in starting_roster:
        print('{:30}, Salary: {:5}, Value: {:.3f}'.format(player['DraftKingsName'], player['DraftKingsSalary'], player['Value']))

        prospects = [prospect for prospect in players if prospect['DraftKingsSalary'] == player['DraftKingsSalary']]

        dedup_prospects = []
        for prospect in prospects:
            found = False

            if prospect['DraftKingsName'] == player['DraftKingsName']:
                found = True
            else:
                for final_player in final_roster:
                    if prospect['DraftKingsName'] == final_player['DraftKingsName']:
                        found = True

            if not found:
                dedup_prospects.append(prospect)

        prospects = dedup_prospects
        prospects = sorted(prospects, key=lambda x: x['Value'], reverse=True)

        for prospect in prospects:
            print('    Prospect: {}, Salary: {:5}, Value: {:.3f}'.format(prospect['DraftKingsName'], prospect['DraftKingsSalary'], prospect['Value']))

        # print(prospects)
        if (len(prospects) > 0):
            if prospects[0]['Value'] > player['Value']:
                final_roster.append(prospects[0])
            else:
                final_roster.append(player)
        else:
            final_roster.append(player)

    print()
    print('Final Roster')
    for player in final_roster:
        print('{:30}, Salary: {:5}, Value: {:.3f}'.format(player['DraftKingsName'], player['DraftKingsSalary'], player['Value']))
    print('Total Points: {:.3f}'.format(sum([player['FantasyPoints'] for player in final_roster])))
    print('Total Salary: {:5}'.format(sum([player['DraftKingsSalary'] for player in final_roster])))

    roster = Roster(final_roster)

    return roster

def autopick(tournament_id, num_rosters):
    players = get_players(tournament_id)

    rosters = []
    for _ in range(num_rosters):
        roster = get_roster(players)
        rosters.append(roster)

    rosters.sort(key=lambda x: x.total_points, reverse=True)

    print()
    print('*********************')
    print('*      ROSTERS      *')
    print('*********************')
    print()
    for roster in rosters:
        print(roster)

def values(tournament_id):
    players = get_players(tournament_id)
    players = sorted(players, key=lambda x: x['Value'], reverse=True)

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

def points(tournament_id):
    players = get_players(tournament_id)
    players = sorted(players, key=lambda x: x['FantasyPoints'], reverse=True)

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

def sandbox():
    pass

def main():
    args = parse_args()

    if args.cmd == 'players':
        player_profiles = fetch_player_profiles()

    elif args.cmd == 'create-leaderboard-table':
        create_leaderboard_table()

    elif args.cmd == 'manage-leaderboard':
        manage_leaderboard(TOURNAMENT_ID, args.round_num)

    elif args.cmd == 'update-leaderboard':
        update_leaderboard(TOURNAMENT_ID)

    elif args.cmd == 'tournaments':
        create_tournaments_table()
        populate_tournaments_table()

    elif args.cmd == 'salaries':
        create_salaries_table()
        populate_salaries_table(TOURNAMENT_ID)

    elif args.cmd == 'autopick':
        autopick(TOURNAMENT_ID, args.num_rosters)

    elif args.cmd == 'values':
        values(TOURNAMENT_ID)

    elif args.cmd == 'points':
        points(TOURNAMENT_ID)

    elif args.cmd == 'picks':
        update_picks()

    elif args.cmd == 'clear-picks':
        create_picks_table()
        update_leaderboard(TOURNAMENT_ID)

    elif args.cmd == 'flask':
        app.run(host='0.0.0.0', port=80, debug=True)
        # app.run(host='0.0.0.0', port=80, debug=False)

    elif args.cmd == 'sandbox':
        sandbox()

if __name__ == '__main__':
    main()
