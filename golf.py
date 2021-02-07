#!/usr/bin/env python3

import argparse
import requests
import json
from pprint import pprint, pformat
from datetime import datetime, timedelta
import time
from prettytable import PrettyTable

KEY = 'a478d29a98e54eac8e9ebf1f218dd0b8'

START_DAY_WINDOW    = 4
END_DAY_WINDOW      = 1
PLAYERS_FILENAME    = 'player_profiles.json'

CMDS = [
    'fixtures',
    'leaderboard',
]

def parse_args():
    description = 'Fantasy Golf Tool'

    parser = argparse.ArgumentParser(description=description, formatter_class=argparse.RawTextHelpFormatter)

    parser.add_argument('cmd', help='Directory path', type=str, choices=CMDS)

    return parser.parse_args()

def request(url):
    payload = {
        'key': KEY,
    }

    r = requests.get(url, params=payload)
    return json.loads(r.text)

def api_get_all_players():
    return request('https://api.sportsdata.io/golf/v2/json/Players')

def api_get_all_tournaments():
    return request('https://api.sportsdata.io/golf/v2/json/Tournaments')

def api_get_leaderboard(tournament_id):
    return request('https://api.sportsdata.io/golf/v2/json/Leaderboard/{}'.format(tournament_id))

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

# def parse_leaderboard(leaderboard, player_profiles):
def parse_leaderboard(leaderboard):
    max_rounds = 0

    entries = []

    num_rounds = len(leaderboard['Tournament']['Rounds'])
    par        = leaderboard['Tournament']['Par']

    table = PrettyTable()
    table.field_names = [
        'Rank',
        'Name',
        'Score',
        'Strokes',
        'Through',
    ]

    for player in leaderboard['Players']:
        # player_profile = get_player_profile(player['PlayerID'], player_profiles)

        # if player_profile is None:
        #     name = 'Unknown PlayerID: {}'.format(player['PlayerID'])
        # else:
        #     name = '{}'.format(player_profile['DraftKingsName'])
        # name = player['Name']

        # # To par calculation
        # to_par = None
        # for player_round in player['Rounds']:
        #     for hole in player_round['Holes']:
        #         if hole['ToPar'] is not None:
        #             if to_par is None:
        #                 to_par = hole['ToPar']
        #             else:
        #                 to_par += int(hole['ToPar'])

        # if to_par is not None:
        #     print('{:3} {}'.format(to_par, name))

            #   'TotalScore': None,
            #   'TotalStrokes': 95.0,
            #   'TotalThrough': None,


        # entries.append({
        #     'name'  : player['Name'],
        #     'rank'  : player['Rank'],
        #     'rounds': [],
        # })

        table.add_row([
            player['Rank'],
            player['Name'],
            player['TotalScore'],
            player['TotalStrokes'],
            player['TotalThrough'],
        ])

        # # Rank
        # if player['Rank'] is not None and player['Name'] is not None:
        #     print('{:3} {} {} {}'.format(player['Rank'], player['Name']))

    print(table)

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
        # parse_leaderboard(leaderboard, player_profiles)
        parse_leaderboard(leaderboard)

if __name__ == '__main__':
    main()
