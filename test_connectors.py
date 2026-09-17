"""
Quick sanity check for each company's connector, run in isolation.

Usage:
    python test_connectors.py                 # test every company
    python test_connectors.py "Aon"            # test just one company

Prints how many postings were found and shows the first 3, so you can
eyeball whether the connector is actually working before relying on it
for the daily run.
"""
import sys

from main import load_companies, CONNECTORS

def main():
    filter_name = sys.argv[1] if len(sys.argv) > 1 else None
    companies = load_companies()

    for company in companies:
        name = company["name"]
        if filter_name and name != filter_name:
            continue

        platform = company.get("platform")
        connector = CONNECTORS.get(platform)
        print(f"\n=== {name} (platform: {platform}) ===")

        if connector is None:
            print("  No connector configured yet for this platform.")
            continue

        try:
            jobs = connector(company)
        except Exception as e:  # noqa: BLE001
            print(f"  FAILED: {e}")
            continue

        print(f"  Found {len(jobs)} postings")
        for j in jobs[:3]:
            print(f"   - {j['title']}  ->  {j['url']}")


if __name__ == "__main__":
    main()
