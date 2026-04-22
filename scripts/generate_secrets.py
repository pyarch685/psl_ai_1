#!/usr/bin/env python3
"""
Generate secure secret keys for production deployment.
"""
from __future__ import annotations

import secrets


def generate_jwt_secret() -> str:
    """Generate a secure JWT secret key."""
    return secrets.token_urlsafe(32)


def main() -> None:
    """Generate and display secret keys."""
    print("=" * 70)
    print("PSL AI - Secret Key Generator")
    print("=" * 70)
    print()
    print("Generated JWT Secret Key:")
    print("-" * 70)
    jwt_secret = generate_jwt_secret()
    print(jwt_secret)
    print("-" * 70)
    print()
    print("Example Railway environment variable:")
    print(f"JWT_SECRET_KEY={jwt_secret}")
    print()
    print("=" * 70)


if __name__ == "__main__":
    main()
