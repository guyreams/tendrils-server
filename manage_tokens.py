"""CLI tool for managing API keys via the running Tendrils Server.

Connects to the server's admin endpoint to create and list users.
The server must be running for this tool to work.

Usage:
    python manage_tokens.py create --owner bot_c --name "Bot C"
    python manage_tokens.py create --owner bot_c --name "Bot C" --url http://myserver:8000
    python manage_tokens.py list
    python manage_tokens.py list --url http://myserver:8000

Environment variables:
    TENDRILS_URL     — Server URL (default: http://127.0.0.1:8000)
    ADMIN_SECRET     — Admin secret for the server (default: change-me-in-production)
"""

import argparse
import os
import sys

import httpx

DEFAULT_URL = os.environ.get("TENDRILS_URL", "http://127.0.0.1:8000")
ADMIN_SECRET = os.environ.get("ADMIN_SECRET", "change-me-in-production")


def create_user(url: str, owner_id: str, name: str) -> None:
    """Register a new user and print their API key."""
    try:
        resp = httpx.post(
            f"{url}/admin/register",
            json={"owner_id": owner_id, "name": name},
            headers={"X-Admin-Secret": ADMIN_SECRET},
            timeout=10.0,
        )
    except httpx.ConnectError:
        print(f"Error: Could not connect to server at {url}", file=sys.stderr)
        print("Is the server running?", file=sys.stderr)
        sys.exit(1)

    if resp.status_code == 200:
        data = resp.json()
        print(f"Registered: {owner_id}")
        print(f"API Key:    {data['api_key']}")
    elif resp.status_code == 409:
        print(f"Error: owner_id '{owner_id}' is already registered", file=sys.stderr)
        sys.exit(1)
    elif resp.status_code == 403:
        print("Error: Invalid admin secret", file=sys.stderr)
        print("Set ADMIN_SECRET env var to match the server's config", file=sys.stderr)
        sys.exit(1)
    else:
        print(f"Error: {resp.status_code} — {resp.text}", file=sys.stderr)
        sys.exit(1)


def list_users(url: str) -> None:
    """List all registered users (requires the admin/users endpoint)."""
    try:
        resp = httpx.get(
            f"{url}/admin/users",
            headers={"X-Admin-Secret": ADMIN_SECRET},
            timeout=10.0,
        )
    except httpx.ConnectError:
        print(f"Error: Could not connect to server at {url}", file=sys.stderr)
        print("Is the server running?", file=sys.stderr)
        sys.exit(1)

    if resp.status_code == 200:
        users = resp.json()
        if not users:
            print("No registered users.")
            return
        print(f"{'OWNER_ID':<20} {'NAME':<20}")
        print("-" * 40)
        for user in users:
            print(f"{user['owner_id']:<20} {user['name']:<20}")
    elif resp.status_code == 403:
        print("Error: Invalid admin secret", file=sys.stderr)
        sys.exit(1)
    else:
        print(f"Error: {resp.status_code} — {resp.text}", file=sys.stderr)
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Manage Tendrils Server API keys",
    )
    parser.add_argument(
        "--url",
        default=DEFAULT_URL,
        help=f"Server URL (default: {DEFAULT_URL}, or set TENDRILS_URL env var)",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    create_parser = subparsers.add_parser("create", help="Register a new user")
    create_parser.add_argument("--owner", required=True, help="Unique owner_id for the bot")
    create_parser.add_argument("--name", required=True, help="Display name for the user")

    subparsers.add_parser("list", help="List all registered users")

    args = parser.parse_args()

    if args.command == "create":
        create_user(args.url, args.owner, args.name)
    elif args.command == "list":
        list_users(args.url)


if __name__ == "__main__":
    main()
