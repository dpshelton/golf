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

KEY = 'a478d29a98e54eac8e9ebf1f218dd0b8'

START_DAY_WINDOW    = 4
END_DAY_WINDOW      = 1
PLAYERS_FILENAME    = 'player_profiles.json'

CMDS = [
    'fixtures',
    'leaderboard',
    'tournaments',
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

def get_player_profile(player_id, player_profiles):
    for player_profile in player_profiles:
        if player_id == player_profile['PlayerID']:
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

        player_profile = get_player_profile(player['PlayerID'], player_profiles)
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

@app.route('/')
def index():
    # name = request.args.get("name", "World")
    # return f'Hello, {escape(name)}!'

    # tournaments = api_get_all_tournaments()

    # response = ''
    # for tournament in tournaments:
    #     start_date = datetime.fromisoformat(tournament['StartDate'])

    #     response += '{},{},{},\n'.format(tournament['Name'], str(start_date.date()), tournament['TournamentID'])

    conn = get_db_connection()
    posts = conn.execute('SELECT * FROM posts').fetchall()
    conn.close()

    return render_template('index.html')

@app.route('/results')
def golf_results():
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
    # tournaments = api_get_all_tournaments()

    # response = ''
    # for tournament in tournaments:
    #     start_date = datetime.fromisoformat(tournament['StartDate'])

    #     response += '{},{},{},\n'.format(tournament['Name'], str(start_date.date()), tournament['TournamentID'])

    # return response

    tournaments = api_get_all_tournaments()
    return render_template('tournaments.html', tournaments=tournaments)

@app.route('/players')
def players():
    player_profiles = load_player_profiles()
    # filtered_player_profiles =
    player_profiles = [player_profile for player_profile in player_profiles if player_profile['DraftKingsName'] is not None]

    return render_template('players.html', players=player_profiles)

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
        tournaments = api_get_all_tournaments()

        pprint(tournaments)

    elif args.cmd == 'flask':
        app.run(host='0.0.0.0', debug=True)

if __name__ == '__main__':
    main()
