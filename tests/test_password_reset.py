"""
Manual test script for password reset functionality.

This script helps test the password reset flow manually.
Run with: python -m tests.test_password_reset

Note: This is a manual test script, not an automated test suite.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Add project root to path
BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

import requests
import json
from time import sleep


BASE_URL = "http://localhost:8000"


def print_section(title: str):
    """Print a section header."""
    print("\n" + "=" * 60)
    print(f" {title}")
    print("=" * 60 + "\n")


def test_forgot_password(email: str):
    """
    Test the forgot password endpoint.
    
    Args:
        email: Email address to request password reset for.
    """
    print_section("Testing Forgot Password Endpoint")
    
    url = f"{BASE_URL}/auth/forgot-password"
    data = {"email": email}
    
    print(f"Sending request to: {url}")
    print(f"Request body: {json.dumps(data, indent=2)}")
    
    try:
        response = requests.post(url, json=data)
        print(f"\nResponse status: {response.status_code}")
        print(f"Response body: {json.dumps(response.json(), indent=2)}")
        
        if response.status_code == 200:
            print("\n✓ Success! Check console output for reset token (if DISABLE_EMAIL=true)")
            print("  or check email inbox for reset link.")
        else:
            print(f"\n✗ Failed with status {response.status_code}")
        
        return response.status_code == 200
        
    except requests.exceptions.ConnectionError:
        print("\n✗ Error: Could not connect to API server.")
        print("  Make sure the API server is running on http://localhost:8000")
        return False
    except Exception as e:
        print(f"\n✗ Error: {e}")
        return False


def test_reset_password(token: str, new_password: str):
    """
    Test the reset password endpoint.
    
    Args:
        token: Reset token from email or console.
        new_password: New password to set.
    """
    print_section("Testing Reset Password Endpoint")
    
    url = f"{BASE_URL}/auth/reset-password"
    data = {
        "token": token,
        "new_password": new_password
    }
    
    print(f"Sending request to: {url}")
    print(f"Request body: {json.dumps({**data, 'new_password': '***'}, indent=2)}")
    
    try:
        response = requests.post(url, json=data)
        print(f"\nResponse status: {response.status_code}")
        print(f"Response body: {json.dumps(response.json(), indent=2)}")
        
        if response.status_code == 200:
            print("\n✓ Success! Password has been reset.")
        else:
            print(f"\n✗ Failed with status {response.status_code}")
        
        return response.status_code == 200
        
    except requests.exceptions.ConnectionError:
        print("\n✗ Error: Could not connect to API server.")
        print("  Make sure the API server is running on http://localhost:8000")
        return False
    except Exception as e:
        print(f"\n✗ Error: {e}")
        return False


def interactive_test():
    """Run an interactive test session."""
    print_section("Password Reset Interactive Test")
    
    print("This script will help you test the password reset functionality.")
    print("Make sure the API server is running before continuing.\n")
    
    # Step 1: Forgot Password
    email = input("Enter email address to test with: ").strip()
    if not email:
        print("No email provided. Exiting.")
        return
    
    success = test_forgot_password(email)
    if not success:
        print("\nTest failed. Please check the error messages above.")
        return
    
    print("\n" + "-" * 60)
    print("If DISABLE_EMAIL=true, copy the token from the console output.")
    print("If DISABLE_EMAIL=false, check your email for the reset link.")
    print("-" * 60 + "\n")
    
    # Step 2: Reset Password
    token = input("Enter reset token: ").strip()
    if not token:
        print("No token provided. Exiting.")
        return
    
    new_password = input("Enter new password (min 8 chars, mixed case, digit, special): ").strip()
    if not new_password:
        print("No password provided. Exiting.")
        return
    
    success = test_reset_password(token, new_password)
    if success:
        print("\n✓ All tests passed!")
        print("  You can now log in with the new password.")
    else:
        print("\nTest failed. Please check the error messages above.")


def quick_test():
    """
    Run a quick automated test with predefined values.
    
    NOTE: This requires a test user to exist.
    """
    print_section("Password Reset Quick Test")
    
    test_email = "test@example.com"
    test_password = "NewPassword123!"
    
    print(f"Testing with email: {test_email}")
    print("This requires the test user to exist in the database.\n")
    
    # Test forgot password
    success = test_forgot_password(test_email)
    if not success:
        return
    
    print("\n⚠ Quick test cannot continue automatically.")
    print("  You need to manually copy the token from console/email.")
    print("  Then run: python -m tests.test_password_reset")
    print("  and select the interactive test option.")


def main():
    """Main entry point."""
    print("\nPassword Reset Test Script")
    print("==========================\n")
    print("Choose test mode:")
    print("1. Interactive test (recommended)")
    print("2. Quick test (forgot password only)")
    print("3. Test forgot password with custom email")
    print("4. Test reset password with custom token")
    
    choice = input("\nEnter choice (1-4): ").strip()
    
    if choice == "1":
        interactive_test()
    elif choice == "2":
        quick_test()
    elif choice == "3":
        email = input("Enter email: ").strip()
        test_forgot_password(email)
    elif choice == "4":
        token = input("Enter token: ").strip()
        password = input("Enter new password: ").strip()
        test_reset_password(token, password)
    else:
        print("Invalid choice. Exiting.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nTest interrupted by user.")
        sys.exit(0)
