#!/usr/bin/env python3
"""Validate FRR JSON responses; an empty or uninstalled route must not pass."""
import argparse
import json
import sys


def peers_ready(data, expected, minimum):
    peers = data.get('ipv4Unicast', data).get('peers', {})
    established = {name for name, peer in peers.items() if peer.get('state') == 'Established'}
    return set(expected).issubset(established) and len(established) >= minimum


def route_ready(data, prefix, expected):
    for route in data.get(prefix, []):
        if route.get('protocol') != 'bgp' or not route.get('selected') or not route.get('installed'):
            continue
        hops = {hop.get('ip') for hop in route.get('nexthops', []) if hop.get('fib')}
        if hops and set(expected).issubset(hops):
            return True
    return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('check', choices=('peers', 'route'))
    parser.add_argument('values', nargs='*')
    parser.add_argument('--minimum', type=int, default=1)
    args = parser.parse_args()
    data = json.load(sys.stdin)
    if args.check == 'peers':
        valid = peers_ready(data, args.values, args.minimum)
    else:
        if not args.values:
            parser.error('route requires a prefix')
        valid = route_ready(data, args.values[0], args.values[1:])
    if not valid:
        raise SystemExit('FRR peers or installed BGP route not ready')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, TypeError, AttributeError) as error:
        raise SystemExit(f'Invalid FRR JSON: {error}')
