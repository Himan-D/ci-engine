#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# CI Engine - CLI

import sys
import argparse
import requests


class CIEngineCLI:
    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url.rstrip("/")

    def do_builds(self, args):
        """List builds."""
        url = f"{self.base_url}/api/builds"
        if args.status:
            url += f"?status={args.status}"
        resp = requests.get(url)
        if resp.status_code != 200:
            print(f"Error: {resp.text}")
            return 1

        builds = resp.json()
        for b in builds:
            print(f"#{b['id']} | {b['branch']} | {b['status']} | {b['created_at'][:19]}")
        return 0

    def do_build_create(self, args):
        """Create a new build."""
        with open(args.pipeline, "r") as f:
            pipeline = f.read()

        resp = requests.post(
            f"{self.base_url}/api/builds",
            json={"pipeline": pipeline, "branch": args.branch},
        )
        if resp.status_code != 200:
            print(f"Error: {resp.text}")
            return 1

        build = resp.json()
        print(f"Created build #{build['id']}")
        return 0

    def do_agents(self, args):
        """List agents."""
        resp = requests.get(f"{self.base_url}/api/agents")
        if resp.status_code != 200:
            print(f"Error: {resp.text}")
            return 1

        agents = resp.json()
        for a in agents:
            print(f"#{a['id']} | {a['name']} | {a['hostname']} | {a['status']}")
        return 0

    def do_stats(self, args):
        """Show stats."""
        resp = requests.get(f"{self.base_url}/api/stats")
        if resp.status_code != 200:
            print(f"Error: {resp.text}")
            return 1

        stats = resp.json()
        print(f"Builds (24h): {stats['builds_24h']}")
        print(f"Total builds: {stats['total_builds']}")
        print(f"Active pipelines: {stats['active_pipelines']}")
        return 0

    def do_status(self, args):
        """Show status."""
        resp = requests.get(f"{self.base_url}/status")
        if resp.status_code != 200:
            print(f"Error: {resp.text}")
            return 1

        status = resp.json()
        print(f"Status: {status['status']}")
        for comp in status.get("components", []):
            print(f"  {comp['name']}: {comp['status']}")
        return 0


def main():
    parser = argparse.ArgumentParser(prog="ci-engine")
    parser.add_argument("--url", default="http://localhost:8000", help="Server URL")

    subparsers = parser.add_subparsers()

    builds_parser = subparsers.add_parser("builds", help="List builds")
    builds_parser.add_argument("--status", choices=["pending", "running", "passed", "failed"])
    builds_parser.set_defaults(func="builds")

    create_parser = subparsers.add_parser("create", help="Create a build")
    create_parser.add_argument("-p", "--pipeline", required=True, help="Pipeline file")
    create_parser.add_argument("-b", "--branch", default="main", help="Branch")
    create_parser.set_defaults(func="build_create")

    agents_parser = subparsers.add_parser("agents", help="List agents")
    agents_parser.set_defaults(func="agents")

    stats_parser = subparsers.add_parser("stats", help="Show stats")
    stats_parser.set_defaults(func="stats")

    status_parser = subparsers.add_parser("status", help="Show status")
    status_parser.set_defaults(func="status")

    args = parser.parse_args()

    if not hasattr(args, "func"):
        parser.print_help()
        return 1

    cli = CIEngineCLI(args.url)
    func = getattr(cli, f"do_{args.func}")
    return func(args)


if __name__ == "__main__":
    sys.exit(main())
