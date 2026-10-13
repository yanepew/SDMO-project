"""
Key provisioning tool.

  python -m common.keygen dev                       # everything, for local demos
  python -m common.keygen cloud                     # cloud key pair
  python -m common.keygen gateway --id gateway-1    # gateway key pair

Distribution (production):
  * copy keys/cloud.public.json    -> gateway host
  * copy keys/gateway.public.json  -> cloud host, keys/trusted_gateways/
  * private files never leave their host.
"""

from __future__ import annotations

import argparse

from common.keystore import KeyRecord, keys_dir, save_key, trusted_gateways_dir
from common.pqc_channel import generate_kem_keypair


def make_cloud_keys() -> None:
    ek, dk = generate_kem_keypair()
    record = KeyRecord("cloud", "cloud", ek, dk)
    save_key(keys_dir() / "cloud.private.json", record, include_private=True)
    save_key(keys_dir() / "cloud.public.json", record, include_private=False)
    print(f"Wrote {keys_dir() / 'cloud.private.json'} and cloud.public.json")


def make_gateway_keys(gateway_id: str, trust_on_this_host: bool = False) -> None:
    ek, dk = generate_kem_keypair()
    record = KeyRecord("gateway", gateway_id, ek, dk)
    save_key(keys_dir() / "gateway.private.json", record, include_private=True)
    save_key(keys_dir() / "gateway.public.json", record, include_private=False)
    print(f"Wrote {keys_dir() / 'gateway.private.json'} and gateway.public.json")
    if trust_on_this_host:
        target = trusted_gateways_dir() / f"{gateway_id}.json"
        save_key(target, record, include_private=False)
        print(f"Registered gateway as trusted: {target}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("cloud")
    gateway = sub.add_parser("gateway")
    gateway.add_argument("--id", default="gateway-1")
    dev = sub.add_parser("dev")
    dev.add_argument("--id", default="gateway-1")
    args = parser.parse_args()

    if args.command == "cloud":
        make_cloud_keys()
    elif args.command == "gateway":
        make_gateway_keys(args.id)
    else:
        make_cloud_keys()
        make_gateway_keys(args.id, trust_on_this_host=True)


if __name__ == "__main__":
    main()
