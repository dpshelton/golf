#!/usr/bin/env python3

import argparse
import requests
import json
from pprint import pprint, pformat
from datetime import datetime, timedelta
import time
from prettytable import PrettyTable
import sqlite3
from flask import Flask, escape, request, render_template
from draft_kings import Sport, Client

KEY = 'a478d29a98e54eac8e9ebf1f218dd0b8'

START_DAY_WINDOW    = 4
END_DAY_WINDOW      = 1
PLAYERS_FILENAME    = 'player_profiles.json'

CMDS = [
    'fixtures',
    'leaderboard',
    'tournaments',
    'sandbox',
    'flask',
]

POINTS = [
    (0 , 0   , 100),
    (1 , 1   , 75),
    (2 , 2   , 50),
    (3 , 3   , 30),
    (4 , 4   , 25),
    (5 , 5   , 20),
    (6 , 6   , 18),
    (7 , 7   , 16),
    (8 , 8   , 14),
    (9 , 9   , 12),
    (10, 14  , 10),
    (15, 19  ,  8),
    (20, 29  ,  6),
    (30, 39  ,  5),
    (40, 49  ,  3),
    (50, 1000,  1),
]

app = Flask(__name__)

def parse_args():
    description = 'Fantasy Golf Tool'

    parser = argparse.ArgumentParser(description=description, formatter_class=argparse.RawTextHelpFormatter)

    parser.add_argument('cmd', help='Directory path', type=str, choices=CMDS)

    return parser.parse_args()

def api_request(url):
    payload = {
        'key': KEY,
    }

    r = requests.get(url, params=payload)
    return json.loads(r.text)

def api_get_all_players():
    return api_request('https://api.sportsdata.io/golf/v2/json/Players')

def api_get_all_tournaments():
    return api_request('https://api.sportsdata.io/golf/v2/json/Tournaments')

def api_get_leaderboard(tournament_id):
    return api_request('https://api.sportsdata.io/golf/v2/json/Leaderboard/{}'.format(tournament_id))

def api_get_projections(tournament_id):
    return api_request('https://api.sportsdata.io/golf/v2/json/PlayerTournamentProjectionStats/{}'.format(tournament_id))

def get_active_tournaments():
    active_tournaments = []

    tournaments = api_get_all_tournaments()
    for tournament in tournaments:
        if tournament['IsInProgress']:
            active_tournaments.append(tournament)

    return active_tournaments

def get_leaderboard(tournament):
    return api_get_leaderboard(tournament['TournamentID'])

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

def get_points(rank):
    if rank is None:
        return 0
    else:
        for start, end, points in POINTS:
            if rank >= start and rank <= end:
                return points

    return 0

def parse_leaderboard(leaderboard, player_profiles):
    # Unscramble the 'Rank' from fantasydata.com
    prev_rank = None
    parsed_leaderboard = []
    rank = None
    for i, player in enumerate(leaderboard['Players']):
        if i == 0:
            rank = int(player['Rank'])
        elif player['Rank'] is None:
            rank = None
        elif player['Rank'] != prev_rank:
            rank = len(parsed_leaderboard)

        player_profile = get_player_profile(player_id=player['PlayerID'], player_profiles=player_profiles)
        parsed_leaderboard.append((
            str(rank),
            player_profile['DraftKingsName'],
            str(get_points(rank)),
        ))

        prev_rank = player['Rank']

    table = PrettyTable()
    table.field_names = [
        'Rank',
        'Name',
        'Points',
    ]

    for player in parsed_leaderboard:
        table.add_row([
            player[0],
            player[1],
            player[2],
        ])

    print(table)

    return parsed_leaderboard

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
            Venue TEXT
        );
    ''')
    conn.commit()
    conn.close()

def populate_tournaments_table():
    tournaments = api_get_all_tournaments()

    conn = get_db_connection()
    curr = conn.cursor()

    for tournament in tournaments:
        curr.execute("INSERT INTO tournaments (TournamentID, Name, StartDate, EndDate, Location, Venue) VALUES (?, ?, ?, ?, ?, ?)", (
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
            DraftKingsSalary INTEGER
        );
    ''')
    conn.commit()
    conn.close()

def populate_salaries_table(tournament_id):
    tournament = get_tournament_from_id(tournament_id)
    if tournament is None:
        return

    player_profiles = load_player_profiles()

    contests = Client().contests(sport=Sport.GOLF)
    for draft_group in contests.draft_groups:
        draft_group_details = Client().draft_group_details(draft_group_id=draft_group.draft_group_id)

        if draft_group_details.games[0].name != tournament['Name']:
            continue
        if draft_group_details.leagues[0].abbreviation != 'PGA':
            continue
        game_type_rules = Client().game_type_rules(game_type_id=draft_group_details.contest_details.type_id)
        if not game_type_rules.salary_cap_details.is_enabled or int(game_type_rules.salary_cap_details.maximum_value) != 50000:
            continue

        draftables = Client().draftables(draft_group_id=draft_group_details.draft_group_id)

        conn = get_db_connection()
        curr = conn.cursor()

        for player in draftables.players:
            player_profile = get_player_profile(draft_kings_player_id=player.player_id, player_profiles=player_profiles)

            if player_profile is not None:
                if player.name_details.display != player_profile['DraftKingsName']:
                    print('Player names do not match {} vs {}'.format(player.name_details.display, player_profile['DraftKingsName']))

                curr.execute("INSERT INTO salaries (TournamentID, PlayerID, DraftKingsPlayerID, DraftKingsName, DraftKingsSalary) VALUES (?, ?, ?, ?, ?)", (
                    tournament_id,
                    player_profile['PlayerID'],
                    player_profile['DraftKingsPlayerID'],
                    player_profile['DraftKingsName'],
                    player.salary,
                ))
            else:
                print('WTF {}'.format(player.name_details.display))

        conn.commit()
        conn.close()

        break

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

#         curr.execute("INSERT INTO salaries (TournamentID, PlayerID, DraftKingsName, DraftKingsSalary) VALUES (?, ?, ?, ?)", (
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

@app.route('/results')
def results():
    tournament_id = request.args.get('tournamentid')

    if tournament_id is None:
        print('tournamentid not specified. Exiting...')
        return

    leaderboard = api_get_leaderboard(tournament_id)
    player_profiles = load_player_profiles()
    parsed_leaderboard = parse_leaderboard(leaderboard, player_profiles)

    response = ''
    for player in parsed_leaderboard:
        if player[0] is None or player[0] == 'None':
            rank = None
        else:
            rank = int(player[0]) + 1

        response += '{},{},{},\n'.format(player[1], rank, player[2])

    return response

@app.route('/tournaments')
def tournaments():
    active_tournaments, upcoming_tournaments, past_tournaments, relevant_tournaments = get_tournaments()

    return render_template('tournaments.html',
        active_tournaments      = active_tournaments,
        upcoming_tournaments    = upcoming_tournaments,
        past_tournaments        = past_tournaments,
    )

@app.route('/picks')
def picks():
    tournament_id = request.args.get('tournamentid')

    active_tournaments, upcoming_tournaments, past_tournaments, relevant_tournaments = get_tournaments()

    selected_tournament = None
    if tournament_id is not None:
        for tournament in relevant_tournaments:
            if int(tournament_id) == int(tournament['TournamentID']):
                selected_tournament = tournament
                break

    if selected_tournament is None:
        selected_string = 'Select a tournament'
        salaries = []
    else:
        selected_string = '{} - {}'.format(tournament['Name'], tournament['StartDate'])
        salaries = get_salaries(selected_tournament['TournamentID'])
        player_profiles = load_player_profiles()

    players = []
    for salary in salaries:
        player_profile = get_player_profile(player_id=salary['PlayerID'], player_profiles=player_profiles)

        if salary['DraftKingsSalary'] is not None:
            players.append({
                'DraftKingsName': player_profile['DraftKingsName'],
                'DraftKingsSalary': salary['DraftKingsSalary'],
            })

    if len(players) > 0:
        players = sorted(players, key=lambda x: x['DraftKingsSalary'], reverse=True)

    return render_template('picks.html', players=players, tournaments=relevant_tournaments, tournamentid=tournament_id, selected_string=selected_string)

def sandbox():
    create_salaries_table()

    player_profiles = load_player_profiles()
    print('hey')
    contests = Client().contests(sport=Sport.GOLF)

    for draft_group in contests.draft_groups:
        draft_group_details = Client().draft_group_details(draft_group_id=draft_group.draft_group_id)
        print(draft_group_details.games[0].name)
        if draft_group_details.leagues[0].abbreviation == 'PGA':
            game_type_rules = Client().game_type_rules(game_type_id=draft_group_details.contest_details.type_id)
            if game_type_rules.salary_cap_details.is_enabled and int(game_type_rules.salary_cap_details.maximum_value) == 50000:
                draftables = Client().draftables(draft_group_id=draft_group_details.draft_group_id)
                for player in draftables.players:
                    player_profile = get_player_profile(draft_kings_player_id=player.player_id, player_profiles=player_profiles)

                    if player_profile is not None:
                        if player.name_details.display != player_profile['DraftKingsName']:
                            print('Player names do not match {} vs {}'.format(player.name_details.display, player_profile['DraftKingsName']))
                        print('{}, {}, {}, {}'.format(player.player_id, player.name_details.display, player_profile['DraftKingsName'], player.salary))
                    else:
                        print('WTF {}'.format(player.name_details.display))

                    # print(player_profile)
                    # print(dir(player))
                    # print(player)


                # print(game_type_rules.salary_cap_details)
            # print(Client().game_type_rules(game_type_id=draft_group_details.contest_details.type_id))
            # print(draft_group_details)

def main():
    args = parse_args()

    if args.cmd == 'fixtures':
        player_profiles = fetch_player_profiles()

    elif args.cmd == 'leaderboard':
        # player_profiles = load_player_profiles()

        active_tournaments = get_active_tournaments()

        if len(active_tournaments) == 0:
            print('No active tournaments. Exiting...')
            return

        tournament = active_tournaments[0]

        print(tournament['Name'])
        leaderboard = get_leaderboard(tournament)
        parse_leaderboard(leaderboard)

    elif args.cmd == 'tournaments':
        create_tournaments_table()
        populate_tournaments_table()

    elif args.cmd == 'flask':
        app.run(host='0.0.0.0', port=80, debug=True)

    elif args.cmd == 'sandbox':
        sandbox()

if __name__ == '__main__':
    main()
