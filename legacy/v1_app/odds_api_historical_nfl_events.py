import requests
import json
import csv
from datetime import datetime

# QUARANTINED 2026-11-26: the Odds API key that was hard-coded here is public in Git history and must be
# regenerated before any use. The Odds API is not used until the user decides it is needed
# (docs/security/odds-api-key-quarantine.md). This archived v1 script refuses to run.
API_KEY = None


def _quarantined():
    raise SystemExit("Odds API access is quarantined (docs/security/odds-api-key-quarantine.md)")
BASE_URL = 'https://api.the-odds-api.com/v4/historical/sports'

def fetch_historical_events(sport, date):
    _quarantined()
    url = f"{BASE_URL}/{sport}/events"
    params = {
        'apiKey': API_KEY,
        'date': date
    }
    
    response = requests.get(url, params=params)
    
    print("Response Headers:")
    for key, value in response.headers.items():
        print(f"{key}: {value}")
    print("\n")
    
    if response.status_code != 200:
        print(f"Error: API request failed with status code {response.status_code}")
        return None
    
    return response.text  # Return raw text instead of parsing JSON

def parse_events(events):
    parsed_events = []
    for event in events:
        parsed_event = {
            'id': event.get('id', ''),
            'sport_key': event.get('sport_key', ''),
            'sport_title': event.get('sport_title', ''),
            'commence_time': event.get('commence_time', ''),
            'home_team': event.get('home_team', ''),
            'away_team': event.get('away_team', ''),
            'bookmakers': len(event.get('bookmakers', []))
        }
        parsed_events.append(parsed_event)
    return parsed_events

def save_to_csv(events, filename):
    if not events:
        print("No events to save.")
        return

    fieldnames = events[0].keys()
    
    with open(filename, 'w', newline='', encoding='utf-8') as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        for event in events:
            writer.writerow(event)
    
    print(f"Data saved to {filename}")

def main():
    sport = 'americanfootball_nfl'
    date = '2023-10-15T12:00:00Z'

    response_text = fetch_historical_events(sport, date)
    
    if response_text is not None:
        print(f"API Response type: {type(response_text)}")
        print(f"API Response content:")
        print(response_text)
        
        try:
            # Try to parse the response as JSON
            events = json.loads(response_text)
            print("\nSuccessfully parsed JSON:")
            print(json.dumps(events, indent=2))
        except json.JSONDecodeError:
            print("\nFailed to parse response as JSON. The response might not be in JSON format.")
        
        # Save raw response to a file for further inspection
        with open('api_response.txt', 'w', encoding='utf-8') as f:
            f.write(response_text)
        print("\nRaw response saved to 'api_response.txt'")
    else:
        print(f"Failed to fetch events for date: {date}")

if __name__ == "__main__":
    main()