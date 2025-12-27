#!/usr/bin/env python3
"""
Generate secure secret keys for production deployment.

This script generates cryptographically secure random strings suitable
for use as JWT secret keys and other security tokens.
"""
import secrets
import sys


def generate_jwt_secret() -> str:
    """
    Generate a secure JWT secret key.
    
    Returns:
        A URL-safe base64-encoded random string (44 characters).
    """
    return secrets.token_urlsafe(32)


def main():
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
    print("To use this secret key:")
    print("1. Copy the key above")
    print("2. Set it as the JWT_SECRET_KEY environment variable in Railway")
    print("3. DO NOT commit this key to version control")
    print()
    print("Example Railway environment variable:")
    print(f'  JWT_SECRET_KEY={jwt_secret}')
    print()
    print("=" * 70)


if __name__ == "__main__":
    main()

