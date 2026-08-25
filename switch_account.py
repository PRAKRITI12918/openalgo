#!/usr/bin/env python3
"""
OpenAlgo Multi-Account Switcher CLI.
Easily switch between different broker accounts (Dhan, Zerodha, Fyers, Angel, etc.) in 1 command.

Usage:
  python switch_account.py list
  python switch_account.py switch <profile_name>
  python switch_account.py current
  python switch_account.py save <profile_name> --broker <broker> --api-key <key> --api-secret <secret>
  python switch_account.py delete <profile_name>
"""

import argparse
import sys
import os

# Ensure project root is in sys.path
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)

from utils.account_manager import (
    delete_account_profile,
    get_active_profile_name,
    list_account_profiles,
    save_account_profile,
    switch_account_profile,
)


def print_banner():
    print("\n" + "=" * 65)
    print("        \033[96mOpenAlgo Multi-Account Switcher\033[0m")
    print("=" * 65)


def cmd_list(args):
    print_banner()
    profiles = list_account_profiles()
    active = get_active_profile_name()

    if not profiles:
        print("\n  No saved account profiles found.")
        print("  Use 'python switch_account.py save <name> ...' to add one.\n")
        return

    print(f"\n  {'STATUS':<10} {'PROFILE NAME':<20} {'BROKER':<12} {'CLIENT ID':<15} {'API KEY (MASKED)':<20}")
    print("  " + "-" * 75)

    for p in profiles:
        status = "\033[92m[*] ACTIVE\033[0m" if p["is_active"] else "   [ ]"
        name_str = f"\033[1m{p['name']}\033[0m" if p["is_active"] else p["name"]
        print(f"  {status:<18} {name_str:<28} {p['broker'].upper():<12} {p['client_id'] or '-':<15} {p['api_key_masked']:<20}")

    print("\n  To switch active account:")
    print("    \033[93mpython switch_account.py switch <profile_name>\033[0m\n")


def cmd_switch(args):
    print_banner()
    name = args.profile_name
    print(f"\n  Switching active account to '\033[93m{name}\033[0m'...")

    success, msg = switch_account_profile(name, restart_server=not args.no_restart)
    if success:
        print(f"\n  \033[92m[SUCCESS]\033[0m {msg}")
        print(f"  Open your browser at: \033[94mhttp://127.0.0.1:5000/broker\033[0m to authenticate.")
    else:
        print(f"\n  \033[91m[ERROR]\033[0m {msg}")
    print()


def cmd_current(args):
    print_banner()
    active = get_active_profile_name()
    profiles = {p["name"]: p for p in list_account_profiles()}

    if active and active in profiles:
        p = profiles[active]
        print(f"\n  Currently Active Account: \033[92m{active}\033[0m")
        print(f"  Broker      : {p['broker'].upper()}")
        print(f"  Client ID   : {p['client_id'] or '-'}")
        print(f"  API Key     : {p['api_key_masked']}")
        print(f"  Redirect URL: {p['redirect_url']}")
    else:
        print(f"\n  Active account: \033[93m{active or 'Unregistered / Custom'}\033[0m")
    print()


def cmd_save(args):
    print_banner()
    success, msg = save_account_profile(
        name=args.profile_name,
        broker=args.broker,
        api_key=args.api_key,
        api_secret=args.api_secret,
        redirect_url=args.redirect_url,
        description=args.description or "",
    )
    if success:
        print(f"\n  \033[92m[SUCCESS]\033[0m {msg}")
        if args.make_active:
            s_ok, s_msg = switch_account_profile(args.profile_name)
            print(f"  {s_msg}")
    else:
        print(f"\n  \033[91m[ERROR]\033[0m {msg}")
    print()


def cmd_delete(args):
    print_banner()
    success, msg = delete_account_profile(args.profile_name)
    if success:
        print(f"\n  \033[92m[SUCCESS]\033[0m {msg}")
    else:
        print(f"\n  \033[91m[ERROR]\033[0m {msg}")
    print()


def main():
    parser = argparse.ArgumentParser(
        description="OpenAlgo Multi-Account Switcher CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", help="Command to execute")

    # List
    p_list = subparsers.add_parser("list", help="List all saved account profiles")
    p_list.set_defaults(func=cmd_list)

    # Current
    p_curr = subparsers.add_parser("current", help="Show currently active account")
    p_curr.set_defaults(func=cmd_current)

    # Switch
    p_switch = subparsers.add_parser("switch", help="Switch active account profile")
    p_switch.add_argument("profile_name", help="Name of the profile to activate")
    p_switch.add_argument("--no-restart", action="store_true", help="Do not restart OpenAlgo server automatically")
    p_switch.set_defaults(func=cmd_switch)

    # Save
    p_save = subparsers.add_parser("save", help="Save a new account profile")
    p_save.add_argument("profile_name", help="Unique name for the account profile (e.g. dhan_main, dhan_2)")
    p_save.add_argument("--broker", required=True, help="Broker name (e.g. dhan, zerodha, fyers)")
    p_save.add_argument("--api-key", required=True, help="Broker API Key / Combined ID")
    p_save.add_argument("--api-secret", required=True, help="Broker API Secret")
    p_save.add_argument("--redirect-url", help="Callback redirect URL (optional)")
    p_save.add_argument("--description", help="Optional description note")
    p_save.add_argument("--make-active", action="store_true", help="Immediately activate this profile after saving")
    p_save.set_defaults(func=cmd_save)

    # Delete
    p_del = subparsers.add_parser("delete", help="Delete an account profile")
    p_del.add_argument("profile_name", help="Name of profile to delete")
    p_del.set_defaults(func=cmd_delete)

    args = parser.parse_args()
    if hasattr(args, "func"):
        args.func(args)
    else:
        cmd_list(args)


if __name__ == "__main__":
    main()
