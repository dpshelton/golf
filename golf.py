#!/usr/bin/env python3

import argparse
import requests
import json
from pprint import pprint, pformat
from datetime import datetime, timedelta
import time
import inspect
from prettytable import PrettyTable
import sqlite3
from flask import Flask, escape, request, render_template
from draft_kings import Sport, Client

TOURNAMENT_ID = 425

KEY = 'a478d29a98e54eac8e9ebf1f218dd0b8'

START_DAY_WINDOW    = 4
END_DAY_WINDOW      = 1
PLAYERS_FILENAME    = 'player_profiles.json'
LEADERBOARD_UPDATE_PERIOD = 15 * 60

CMDS = [
    'fixtures',
    'manage-leaderboard',
    'update-leaderboard',
    'create-leaderboard-table',
    'tournaments',
    'sandbox',
    'flask',
]

POINTS = [
    (1 , 1   , 100),
    (2 , 2   , 75),
    (3 , 3   , 50),
    (4 , 4   , 30),
    (5 , 5   , 25),
    (6 , 6   , 20),
    (7 , 7   , 18),
    (8 , 8   , 16),
    (9 , 9   , 14),
    (10, 10  , 12),
    (11, 15  , 10),
    (16, 20  ,  8),
    (21, 30  ,  6),
    (31, 40  ,  5),
    (41, 50  ,  3),
    (51, 1000,  1),
]

OWNERS = [
    'Ben',
    'Greg',
    'Mike',
    'Don',
    'Sean',
]

app = Flask(__name__)

def parse_args():
    description = 'Fantasy Golf Tool'

    parser = argparse.ArgumentParser(description=description, formatter_class=argparse.RawTextHelpFormatter)

    parser.add_argument('cmd', help='Directory path', type=str, choices=CMDS)
    parser.add_argument('-r', '--round-num', help='Round number', type=int, default=1)

    return parser.parse_args()

def api_request(url):
    payload = {
        'key': KEY,
    }

    r = requests.get(url, params=payload)
    return json.loads(r.text)

def api_get_all_players():
    print('API-CALL: {}'.format(inspect.currentframe().f_code.co_name))
    return api_request('https://api.sportsdata.io/golf/v2/json/Players')

def api_get_all_tournaments():
    print('API-CALL: {}'.format(inspect.currentframe().f_code.co_name))
    return api_request('https://api.sportsdata.io/golf/v2/json/Tournaments')

def api_get_leaderboard(tournament_id):
    print('API-CALL: {}'.format(inspect.currentframe().f_code.co_name))
    return api_request('https://api.sportsdata.io/golf/v2/json/Leaderboard/{}'.format(tournament_id))

def api_get_projections(tournament_id):
    print('API-CALL: {}'.format(inspect.currentframe().f_code.co_name))
    return api_request('https://api.sportsdata.io/golf/v2/json/PlayerTournamentProjectionStats/{}'.format(tournament_id))

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
                'Points'            : str(get_points(rank)),
            })
        else:
            rank = None

            unranked_leaderboard.append({
                'PlayerID'          : player['PlayerID'],
                'Rank'              : str(rank),
                'DraftKingsPlayerID': player_profile['DraftKingsPlayerID'],
                'DraftKingsName'    : player_profile['DraftKingsName'],
                'Points'            : str(get_points(rank)),
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

                curr.execute('INSERT INTO salaries (TournamentID, PlayerID, DraftKingsPlayerID, DraftKingsName, DraftKingsSalary) VALUES (?, ?, ?, ?, ?)', (
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

    leaderboard, last_updated = get_leaderboard(tournament_id)

    player_profiles = load_player_profiles()
    picks = get_picks()

    edited_picks = {}
    totals = {}
    for owner in OWNERS:
        edited_picks[owner] = []
        totals[owner] = 0
        for pick in picks[owner]:
            player_profile = get_player_profile(player_id=pick['PlayerID'], player_profiles=player_profiles)
            standing = get_player_standing(pick['PlayerID'], leaderboard)
            if standing is None:
                print('Failed to find {} ({}) in leaderbaord'.format(player_profile['DraftKingsName'], pick['PlayerID']))
            else:
                totals[owner] += int(standing['Points'])
                edited_picks[owner].append({
                    'DraftKingsName': player_profile['DraftKingsName'],
                    'Rank'          : standing['Rank'],
                    'Points'        : standing['Points'],
                    'PhotoUrl'      : player_profile['PhotoUrl'],
                })

    totals = dict(sorted(totals.items(), key=lambda item: item[1], reverse=True))

    return render_template('results.html', leaderboard=leaderboard, picks=edited_picks, totals=totals, owners=OWNERS, last_updated=last_updated)

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
            curr.execute('INSERT INTO leaderboards (TournamentID, PlayerID, Rank, DraftKingsPlayerID, DraftKingsName, Points, Position) VALUES (?, ?, ?, ?, ?, ?, ?)', (
                tournament_id,
                player['PlayerID'],
                player['Rank'],
                player['DraftKingsPlayerID'],
                player['DraftKingsName'],
                player['Points'],
                position,
            ))
        else:
            curr.execute('UPDATE leaderboards SET Rank=?, Points=?, Position=? WHERE TournamentID==? AND PlayerID==?', (
                player['Rank'],
                player['Points'],
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
            PlayerID INTEGER NOT NULL
        );
    ''')
    conn.commit()
    conn.close()

def add_pick(owner, tournament_id, player_name):
    conn = get_db_connection()
    curr = conn.cursor()

    # TODO: load player profiles once
    player_profiles = load_player_profiles()
    player_id = get_player_id_from_name(player_name, player_profiles)

    if player_id is not None:
        curr.execute('INSERT INTO picks (Owner, TournamentID, PlayerID) VALUES (?, ?, ?)', (owner, tournament_id, player_id))
    else:
        print('No player ID for {}. Cannot add to picks.'.format(player_name))

    conn.commit()
    conn.close()

def add_picks():
    conn = get_db_connection()
    curr = conn.cursor()

    add_pick('Ben', TOURNAMENT_ID, 'Jon Rahm')
    add_pick('Ben', TOURNAMENT_ID, 'Tony Finau')
    add_pick('Ben', TOURNAMENT_ID, 'Viktor Hovland')
    add_pick('Ben', TOURNAMENT_ID, 'Carlos Ortiz')
    add_pick('Ben', TOURNAMENT_ID, 'Talor Gooch')
    add_pick('Ben', TOURNAMENT_ID, 'Doc Redman')

    add_pick('Greg', TOURNAMENT_ID, 'Bryson DeChambeau')
    add_pick('Greg', TOURNAMENT_ID, 'Collin Morikawa')
    add_pick('Greg', TOURNAMENT_ID, 'Viktor Hovland')
    add_pick('Greg', TOURNAMENT_ID, 'Max Homa')
    add_pick('Greg', TOURNAMENT_ID, 'Doug Ghim')
    add_pick('Greg', TOURNAMENT_ID, 'Charl Schwartzel')

    add_pick('Mike', TOURNAMENT_ID, 'Viktor Hovland')
    add_pick('Mike', TOURNAMENT_ID, 'Tony Finau')
    add_pick('Mike', TOURNAMENT_ID, 'Jon Rahm')
    add_pick('Mike', TOURNAMENT_ID, 'Kyoung-Hoon Lee')
    add_pick('Mike', TOURNAMENT_ID, 'Carlos Ortiz')
    add_pick('Mike', TOURNAMENT_ID, 'Michael Thompson')

    add_pick('Don', TOURNAMENT_ID, 'Jon Rahm')
    add_pick('Don', TOURNAMENT_ID, 'Jordan Spieth')
    add_pick('Don', TOURNAMENT_ID, 'Cameron Smith')
    add_pick('Don', TOURNAMENT_ID, 'Taehoon Kim')
    add_pick('Don', TOURNAMENT_ID, 'Danny Lee')
    add_pick('Don', TOURNAMENT_ID, 'Xander Schauffele')

    add_pick('Sean', TOURNAMENT_ID, 'Dustin Johnson')
    add_pick('Sean', TOURNAMENT_ID, 'Rory McIlroy')
    add_pick('Sean', TOURNAMENT_ID, 'Xander Schauffele')
    add_pick('Sean', TOURNAMENT_ID, 'Bo Hoag')
    add_pick('Sean', TOURNAMENT_ID, 'Brian Gay')
    add_pick('Sean', TOURNAMENT_ID, 'Danny Lee')

    conn.commit()
    conn.close()

def get_picks():
    conn = get_db_connection()
    curr = conn.cursor()

    picks = {}
    for owner in OWNERS:
        picks[owner] = conn.execute('SELECT * FROM picks WHERE Owner == ?', (
            owner,
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

    while round_num <= num_rounds:
        if first_iteration:
            first_iteration = False
        else:
            leaderboard = api_get_leaderboard(tournament_id)
        update_leaderboard(tournament_id, leaderboard)

        wait_for_round_start(leaderboard, round_num)

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

        if round_complete:
            print('Round {} is over.'.format(round_num))
            round_num += 1
        else:
            print('Sleeping for {} seconds'.format(LEADERBOARD_UPDATE_PERIOD))
            time.sleep(LEADERBOARD_UPDATE_PERIOD)

def wait_for_round_start(leaderboard, round_num):
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

def sandbox():
    # create_leaderboard_table()
    # update_leaderboard(TOURNAMENT_ID)

    # create_picks_table()
    # add_picks()

    # pprint(api_get_all_tournaments())

    # pprint(api_get_leaderboard(TOURNAMENT_ID))

    # leaderboard = api_get_leaderboard(TOURNAMENT_ID)
    # wait_for_round_start(leaderboard=leaderboard, round_num=3)

    manage_leaderboard(TOURNAMENT_ID, starting_round_num=3)

def main():
    args = parse_args()

    if args.cmd == 'fixtures':
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

    elif args.cmd == 'flask':
        app.run(host='0.0.0.0', port=80, debug=True)

    elif args.cmd == 'sandbox':
        sandbox()

if __name__ == '__main__':
    main()
