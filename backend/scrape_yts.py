#!/usr/bin/env python3
"""CLI: scrape movies from yts.bz into SQLite."""

import argparse

from scraper import run_scrape


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape YTS movies into SQLite")
    parser.add_argument("-n", "--count", type=int, default=10, help="Number of movies")
    args = parser.parse_args()
    print(f"Scraping {args.count} movies...")
    result = run_scrape(args.count)
    print(f"Saved {result['saved']} movies (total in DB: {result['total_in_db']})")
    for line in result.get("logs", []):
        print(f"  {line}")


if __name__ == "__main__":
    main()
