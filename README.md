# GT Golf Club

Personal fantasy golf pool for five owners: Ben, Greg, Mike, Don, and Sean. Each owner takes six PGA Tour golfers for one tournament. Finishing position turns into pool points, and a small website shows the standings next to the tournament leaderboard.

Scores come from [SportsData.io](https://sportsdata.io/). The app stores tournaments, DraftKings salaries, leaderboards, and picks in a local SQLite file (`database.db`).

## Scoring

Regular picks use this table. Places 61 through 1000 score 3 points. Anyone else still on the course but outside the table scores 0.

| Place | Points |
| --- | ---: |
| 1 | 150 |
| 2 | 75 |
| 3 | 50 |
| 4 | 35 |
| 5 | 30 |
| 6 | 25 |
| 7 | 20 |
| 8 | 18 |
| 9 | 16 |
| 10 | 14 |
| 11–15 | 12 |
| 16–20 | 10 |
| 21–25 | 8 |
| 26–30 | 7 |
| 31–40 | 6 |
| 41–50 | 5 |
| 51–60 | 4 |
| 61–1000 | 3 |

Ties use competition ranking. Two golfers tied for second both score second-place points, and the next golfer is fourth. Golfers with no score yet are unranked and score 0.

Set `MAJOR = True` in `golf.py` to double every award for a major. One-and-done picks use a shorter top-10 table (50 points for a win, down to 3 for tenth). That path is currently off: `ONE_N_DONES` is not written into the picks table.

The standings page also shifts SportsData tee times three hours earlier (Eastern source, Pacific display). If a tee time was more than an hour ago and the feed has no holes-through value, the golfer is shown as `F`. The feed does not send that marker itself.

## Setup

Python 3.10 or newer.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

The repo already includes:

- `database.db`, a snapshot through the 2024 Farmers Insurance Open (tournament `585`)
- `player_profiles.json`, the golfer directory used to turn names into ids
- `headshots.json`, a saved headshot catalog
- `examples/`, sample API payloads that the app does not read

Because that snapshot is from January 2024, the Tournaments page is empty until the calendar is refreshed. Refreshing calls the network.

## Run the site

```bash
python3 golf.py flask
```

The server listens on `0.0.0.0` port `80` with the Flask debugger on, so it needs permission to bind that port. Pages:

- `/` home
- `/tournaments` active, upcoming, and past events in the last year
- `/results` standings for `TOURNAMENT_ID`, refreshed by the browser every 60 seconds

Green "updated" text means the leaderboard was written within about ten minutes. Older stamps are red.

`templates/picks.html`, `templates/login.html`, and `templates/scorecard.html` are not wired to routes.

## Commands

```bash
python3 golf.py players                 # refresh player_profiles.json
python3 golf.py tournaments             # rebuild the tournament calendar
python3 golf.py salaries                # rebuild DraftKings salaries for TOURNAMENT_ID
python3 golf.py picks                   # replace picks with the PICKS constant
python3 golf.py update-leaderboard      # fetch the leaderboard once
python3 golf.py manage-leaderboard      # poll from round 1 until the event ends
python3 golf.py manage-leaderboard -r 2 # start polling at round 2
python3 golf.py create-leaderboard-table
python3 golf.py clear-picks             # drop picks and refresh the leaderboard
python3 golf.py values                  # project value, highest first
python3 golf.py points                  # project fantasy points, highest first
python3 golf.py autopick                # search one DraftKings lineup
python3 golf.py autopick -n 5           # search five lineups
python3 golf.py sandbox                 # print the headshot feed
```

`manage-leaderboard` sleeps until the first tee time, then every 10 minutes. It treats a round as over once the last tee time has passed and nobody still has a holes-through value, then sleeps an hour before the next round. The first round rebuilds picks when tee times are posted.

`values`, `points`, and `autopick` need salaries in the database. They call the API only when that tournament has no salary rows yet. Value is projected fantasy points per million dollars of salary. Autopick samples one million random six-golfer lineups under the $50,000 cap, then swaps in a better value at the same salary when one exists.

## Change the week

Edit the top of `golf.py`:

- `TOURNAMENT_ID` is the event the site and the CLI use
- `MAJOR` doubles points
- `PICKS` is the five lineups, using DraftKings display names
- `KEY` is the SportsData.io API key

Then load data and picks:

```bash
python3 golf.py tournaments
python3 golf.py players
python3 golf.py salaries
python3 golf.py picks
python3 golf.py update-leaderboard
```

## Tests

```bash
python3 -m unittest discover -s tests -v
```

The tests copy `database.db` and do not call the network. They cover the points table, tie ranking, tee-time conversion, the saved Farmers standings, salary math, and the three web pages.
