"""CLI tool for managing API keys via the running Tendrils Server.

Connects to the server's admin endpoint to create and list users.
The server must be running for this tool to work.

Usage:
    python manage_tokens.py create --owner bot_c --name "Bot C"
    python manage_tokens.py list
    python manage_tokens.py get-token --owner bot_c
    python manage_tokens.py edit --owner bot_c --name "New Name"
    python manage_tokens.py rotate --owner bot_c
    python manage_tokens.py delete --owner bot_c

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


def _request(method: str, url: str, **kwargs) -> httpx.Response:
    """Make an HTTP request with admin secret, handling connection errors."""
    kwargs.setdefault("headers", {})["X-Admin-Secret"] = ADMIN_SECRET
    kwargs.setdefault("timeout", 10.0)
    try:
        return httpx.request(method, url, **kwargs)
    except httpx.ConnectError:
        print(f"Error: Could not connect to server at {url}", file=sys.stderr)
        print("Is the server running?", file=sys.stderr)
        sys.exit(1)


def _handle_error(resp: httpx.Response) -> None:
    """Handle common error status codes."""
    if resp.status_code == 403:
        print("Error: Invalid admin secret", file=sys.stderr)
        print("Set ADMIN_SECRET env var to match the server's config", file=sys.stderr)
        sys.exit(1)
    elif resp.status_code == 404:
        detail = resp.json().get("detail", "Not found")
        print(f"Error: {detail}", file=sys.stderr)
        sys.exit(1)
    elif resp.status_code == 409:
        detail = resp.json().get("detail", "Conflict")
        print(f"Error: {detail}", file=sys.stderr)
        sys.exit(1)
    elif resp.status_code != 200:
        print(f"Error: {resp.status_code} — {resp.text}", file=sys.stderr)
        sys.exit(1)


def create_user(url: str, owner_id: str, name: str) -> None:
    """Register a new user and print their API key."""
    resp = _request("POST", f"{url}/admin/register", json={"owner_id": owner_id, "name": name})
    _handle_error(resp)
    data = resp.json()
    print(f"Registered: {owner_id}")
    print(f"API Key:    {data['api_key']}")


def list_users(url: str) -> None:
    """List all registered users."""
    resp = _request("GET", f"{url}/admin/users")
    _handle_error(resp)
    users = resp.json()
    if not users:
        print("No registered users.")
        return
    print(f"{'OWNER_ID':<20} {'NAME':<20}")
    print("-" * 40)
    for user in users:
        print(f"{user['owner_id']:<20} {user['name']:<20}")


def get_token(url: str, owner_id: str) -> None:
    """Retrieve the API key for a specific user."""
    resp = _request("GET", f"{url}/admin/users/{owner_id}/token")
    _handle_error(resp)
    data = resp.json()
    print(f"Owner:   {data['owner_id']}")
    print(f"API Key: {data['api_key']}")


def edit_user(url: str, owner_id: str, name: str) -> None:
    """Update a user's display name."""
    resp = _request("PATCH", f"{url}/admin/users/{owner_id}", json={"name": name})
    _handle_error(resp)
    data = resp.json()
    print(f"Updated: {data['owner_id']}")
    print(f"Name:    {data['name']}")


def rotate_user_token(url: str, owner_id: str) -> None:
    """Rotate the API key for a user (invalidates old key)."""
    resp = _request("POST", f"{url}/admin/users/{owner_id}/rotate-token")
    _handle_error(resp)
    data = resp.json()
    print(f"Rotated:     {data['owner_id']}")
    print(f"New API Key: {data['api_key']}")


def delete_user(url: str, owner_id: str) -> None:
    """Delete a user and their API key."""
    resp = _request("DELETE", f"{url}/admin/users/{owner_id}")
    _handle_error(resp)
    data = resp.json()
    print(data["message"])
    if data.get("character_removed"):
        print("In-game character was also removed.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Manage Tendrils Server API keys",
    )

    url_kwargs = dict(
        default=DEFAULT_URL,
        help=f"Server URL (default: {DEFAULT_URL}, or set TENDRILS_URL env var)",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    create_parser = subparsers.add_parser("create", help="Register a new user")
    create_parser.add_argument("--owner", required=True, help="Unique owner_id for the bot")
    create_parser.add_argument("--name", required=True, help="Display name for the user")
    create_parser.add_argument("--url", **url_kwargs)

    list_parser = subparsers.add_parser("list", help="List all registered users")
    list_parser.add_argument("--url", **url_kwargs)

    get_token_parser = subparsers.add_parser("get-token", help="Retrieve API key for a user")
    get_token_parser.add_argument("--owner", required=True, help="owner_id to look up")
    get_token_parser.add_argument("--url", **url_kwargs)

    edit_parser = subparsers.add_parser("edit", help="Update a user's display name")
    edit_parser.add_argument("--owner", required=True, help="owner_id to update")
    edit_parser.add_argument("--name", required=True, help="New display name")
    edit_parser.add_argument("--url", **url_kwargs)

    rotate_parser = subparsers.add_parser("rotate", help="Rotate API key (invalidates old key)")
    rotate_parser.add_argument("--owner", required=True, help="owner_id to rotate")
    rotate_parser.add_argument("--url", **url_kwargs)

    delete_parser = subparsers.add_parser("delete", help="Delete a user and their API key")
    delete_parser.add_argument("--owner", required=True, help="owner_id to delete")
    delete_parser.add_argument("--url", **url_kwargs)

    args = parser.parse_args()

    if args.command == "create":
        create_user(args.url, args.owner, args.name)
    elif args.command == "list":
        list_users(args.url)
    elif args.command == "get-token":
        get_token(args.url, args.owner)
    elif args.command == "edit":
        edit_user(args.url, args.owner, args.name)
    elif args.command == "rotate":
        rotate_user_token(args.url, args.owner)
    elif args.command == "delete":
        delete_user(args.url, args.owner)


if __name__ == "__main__":
    main()
