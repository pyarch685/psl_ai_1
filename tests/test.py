"""
Comprehensive tests for PSL Soccer Predictor API.

Tests cover:
- User registration (with validation)
- User login and authentication
- Fixtures endpoint (authentication required)
- Single match predictor (no authentication required)
"""

import requests
import random
import sys
from typing import Optional, Dict, Any
from datetime import datetime


# Configuration
API_BASE_URL = "http://localhost:8000"
TIMEOUT = 5


class Colors:
    """ANSI color codes for terminal output."""
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    END = '\033[0m'
    BOLD = '\033[1m'


def print_section(title: str) -> None:
    """Print a formatted section header."""
    print()
    print("=" * 70)
    print(f"{Colors.BOLD}{title}{Colors.END}")
    print("=" * 70)
    print()


def print_test(test_name: str) -> None:
    """Print a formatted test name."""
    print(f"{Colors.BLUE}{test_name}{Colors.END}")


def print_success(message: str) -> None:
    """Print a success message."""
    print(f"   {Colors.GREEN}✓{Colors.END} {message}")


def print_failure(message: str) -> None:
    """Print a failure message."""
    print(f"   {Colors.RED}✗{Colors.END} {message}")


def print_info(message: str) -> None:
    """Print an info message."""
    print(f"   {Colors.YELLOW}ℹ{Colors.END} {message}")


class TestResults:
    """Track test results."""
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.total = 0
    
    def add_pass(self):
        self.passed += 1
        self.total += 1
    
    def add_fail(self):
        self.failed += 1
        self.total += 1
    
    def summary(self) -> None:
        """Print test summary."""
        print()
        print("=" * 70)
        print(f"{Colors.BOLD}TEST SUMMARY{Colors.END}")
        print("=" * 70)
        print()
        print(f"Total tests: {self.total}")
        print(f"{Colors.GREEN}Passed: {self.passed}{Colors.END}")
        if self.failed > 0:
            print(f"{Colors.RED}Failed: {self.failed}{Colors.END}")
        else:
            print(f"Failed: {self.failed}")
        print()
        if self.failed == 0:
            print(f"{Colors.GREEN}{Colors.BOLD}ALL TESTS PASSED!{Colors.END}")
        else:
            print(f"{Colors.RED}{Colors.BOLD}SOME TESTS FAILED{Colors.END}")
        print("=" * 70)


# Global test results tracker
results = TestResults()


def test_registration() -> Optional[str]:
    """Test user registration functionality."""
    print_section("1. TESTING REGISTRATION")
    
    # Generate unique email for testing
    test_email = f"testuser{random.randint(10000, 99999)}@example.com"
    test_password = "Test123!@#"
    registration_success = False
    
    # Test 1a: Valid registration
    print_test(f"1a. Registering new user: {test_email}")
    try:
        response = requests.post(
            f'{API_BASE_URL}/auth/register',
            json={"email": test_email, "password": test_password},
            timeout=TIMEOUT
        )
        if response.ok:
            data = response.json()
            print_success("Registration successful")
            print_info(f"User ID: {data.get('user_id')}")
            print_info(f"Message: {data.get('message')}")
            results.add_pass()
            registration_success = True
        else:
            data = response.json() if response.text else {}
            print_failure(f"Registration failed: {data.get('detail', response.text[:100])}")
            results.add_fail()
    except Exception as e:
        print_failure(f"Error: {e}")
        results.add_fail()
    
    print()
    
    # Test 1b: Duplicate email (only if registration was successful)
    if registration_success:
        print_test("1b. Testing duplicate email rejection...")
        try:
            response = requests.post(
                f'{API_BASE_URL}/auth/register',
                json={"email": test_email, "password": test_password},
                timeout=TIMEOUT
            )
            if response.status_code == 409:
                data = response.json()
                print_success("Correctly rejected duplicate email")
                print_info(f"Message: {data.get('detail')}")
                results.add_pass()
            else:
                print_failure(f"Unexpected response: {response.status_code}")
                results.add_fail()
        except Exception as e:
            print_failure(f"Error: {e}")
            results.add_fail()
    else:
        print_test("1b. Skipped (initial registration failed)")
        results.add_fail()
    
    print()
    
    # Test 1c: Weak password
    print_test("1c. Testing weak password validation...")
    try:
        response = requests.post(
            f'{API_BASE_URL}/auth/register',
            json={"email": f"weak{random.randint(10000, 99999)}@example.com", "password": "weak"},
            timeout=TIMEOUT
        )
        if response.status_code == 400:
            data = response.json()
            print_success("Correctly rejected weak password")
            print_info(f"Reason: {data.get('detail', '')[:80]}")
            results.add_pass()
        else:
            print_failure(f"Unexpected response: {response.status_code}")
            results.add_fail()
    except Exception as e:
        print_failure(f"Error: {e}")
        results.add_fail()
    
    print()
    
    # Test 1d: Invalid email format
    print_test("1d. Testing invalid email format...")
    try:
        response = requests.post(
            f'{API_BASE_URL}/auth/register',
            json={"email": "not-an-email", "password": test_password},
            timeout=TIMEOUT
        )
        if response.status_code == 400:
            data = response.json()
            print_success("Correctly rejected invalid email")
            print_info(f"Reason: {data.get('detail', '')[:80]}")
            results.add_pass()
        else:
            print_failure(f"Unexpected response: {response.status_code}")
            results.add_fail()
    except Exception as e:
        print_failure(f"Error: {e}")
        results.add_fail()
    
    # Return email only if registration was successful
    return test_email if registration_success else None


def test_login(test_email: Optional[str], test_password: str = "Test123!@#") -> Optional[str]:
    """Test user login functionality."""
    print_section("2. TESTING LOGIN")
    
    if not test_email:
        print_failure("No test email available, skipping login tests")
        return None
    
    # Test 2a: Successful login
    print_test(f"2a. Logging in with correct credentials...")
    try:
        response = requests.post(
            f'{API_BASE_URL}/auth/login',
            json={"email": test_email, "password": test_password},
            timeout=TIMEOUT
        )
        if response.ok:
            data = response.json()
            token = data.get('access_token')
            user_id = data.get('user_id')
            print_success("Login successful")
            print_info(f"User ID: {user_id}")
            print_info(f"Token received: {token[:50] if token else 'None'}...")
            print_info(f"Token type: {data.get('token_type')}")
            results.add_pass()
            return token  # Return token for fixtures tests
        else:
            data = response.json() if response.text else {}
            print_failure(f"Login failed: {data.get('detail', response.text[:100])}")
            results.add_fail()
            return None
    except Exception as e:
        print_failure(f"Error: {e}")
        results.add_fail()
        return None
    
    print()
    
    # Test 2b: Wrong password
    print_test("2b. Testing login with wrong password...")
    try:
        response = requests.post(
            f'{API_BASE_URL}/auth/login',
            json={"email": test_email, "password": "WrongPassword123!"},
            timeout=TIMEOUT
        )
        if response.status_code == 401:
            data = response.json()
            print_success("Correctly rejected wrong password")
            print_info(f"Message: {data.get('detail')}")
            results.add_pass()
        else:
            print_failure(f"Unexpected response: {response.status_code}")
            results.add_fail()
    except Exception as e:
        print_failure(f"Error: {e}")
        results.add_fail()
    
    print()
    
    # Test 2c: Non-existent email
    print_test("2c. Testing login with non-existent email...")
    try:
        response = requests.post(
            f'{API_BASE_URL}/auth/login',
            json={"email": "nonexistent@example.com", "password": test_password},
            timeout=TIMEOUT
        )
        if response.status_code == 401:
            data = response.json()
            print_success("Correctly rejected non-existent email")
            print_info(f"Message: {data.get('detail')}")
            results.add_pass()
        else:
            print_failure(f"Unexpected response: {response.status_code}")
            results.add_fail()
    except Exception as e:
        print_failure(f"Error: {e}")
        results.add_fail()
    
    return token


def test_fixtures(test_token: Optional[str]) -> None:
    """Test fixtures endpoint functionality."""
    print_section("3. TESTING FIXTURES ENDPOINT")
    
    # Test 3a: Access without authentication
    print_test("3a. Testing fixtures WITHOUT authentication...")
    try:
        response = requests.get(
            f'{API_BASE_URL}/fixtures?days=90&limit=5',
            timeout=TIMEOUT
        )
        if response.status_code == 401:
            data = response.json() if response.text else {}
            print_success("Correctly requires authentication")
            print_info(f"Message: {data.get('detail', 'Unauthorized')}")
            results.add_pass()
        else:
            print_failure(f"Unexpected response: {response.status_code}")
            print_info(f"Response: {response.text[:100]}")
            results.add_fail()
    except Exception as e:
        print_failure(f"Error: {e}")
        results.add_fail()
    
    print()
    
    # Test 3b: Access with authentication
    if test_token:
        print_test("3b. Testing fixtures WITH authentication...")
        try:
            headers = {"Authorization": f"Bearer {test_token}"}
            response = requests.get(
                f'{API_BASE_URL}/fixtures?days=90&limit=5',
                headers=headers,
                timeout=TIMEOUT
            )
            if response.ok:
                data = response.json()
                count = data.get('count', 0)
                fixtures = data.get('fixtures', [])
                print_success("Fixtures loaded successfully")
                print_info(f"Fixtures count: {count}")
                if count > 0:
                    print_info("First fixture:")
                    first = fixtures[0]
                    print_info(f"  - {first.get('home_team')} vs {first.get('away_team')}")
                    print_info(f"  - Date: {first.get('date')} at {first.get('time')}")
                    print_info(f"  - Venue: {first.get('venue')}")
                    confidence = first.get('confidence', 0)
                    if isinstance(confidence, float):
                        print_info(f"  - Prediction: {first.get('predicted_outcome')} ({confidence:.1%} confidence)")
                    else:
                        print_info(f"  - Prediction: {first.get('predicted_outcome')}")
                results.add_pass()
            else:
                data = response.json() if response.text else {}
                print_failure(f"Failed: {data.get('detail', response.text[:100])}")
                results.add_fail()
        except Exception as e:
            print_failure(f"Error: {e}")
            results.add_fail()
    else:
        print_test("3b. Skipped (no token available)")
        results.add_fail()
    
    print()
    
    # Test 3c: Invalid token
    print_test("3c. Testing fixtures with invalid token...")
    try:
        headers = {"Authorization": "Bearer invalid_token_12345"}
        response = requests.get(
            f'{API_BASE_URL}/fixtures?days=90&limit=5',
            headers=headers,
            timeout=TIMEOUT
        )
        if response.status_code == 401:
            data = response.json() if response.text else {}
            print_success("Correctly rejected invalid token")
            print_info(f"Message: {data.get('detail', 'Unauthorized')}")
            results.add_pass()
        else:
            print_failure(f"Unexpected response: {response.status_code}")
            results.add_fail()
    except Exception as e:
        print_failure(f"Error: {e}")
        results.add_fail()


def test_predict() -> None:
    """Test single match predictor (no auth required)."""
    print_section("4. TESTING SINGLE MATCH PREDICTOR (No auth required)")
    
    print_test("4a. Testing /predict endpoint without authentication...")
    try:
        response = requests.post(
            f'{API_BASE_URL}/predict',
            json={"home_team": "Orlando Pirates", "away_team": "Kaizer Chiefs"},
            timeout=TIMEOUT
        )
        if response.ok:
            data = response.json()
            print_success("Prediction successful (no auth required)")
            print_info(f"Match: {data.get('home_team')} vs {data.get('away_team')}")
            print_info(f"Prediction: {data.get('predicted_outcome')}")
            probs = data.get('probabilities', {})
            if probs:
                print_info("Probabilities:")
                for outcome, prob in probs.items():
                    if isinstance(prob, (int, float)):
                        print_info(f"  - {outcome}: {prob:.1%}")
                    else:
                        print_info(f"  - {outcome}: {prob}")
            results.add_pass()
        else:
            data = response.json() if response.text else {}
            print_failure(f"Failed: {data.get('detail', response.text[:100])}")
            results.add_fail()
    except Exception as e:
        print_failure(f"Error: {e}")
        results.add_fail()


def check_api_health() -> bool:
    """Check if API is available."""
    try:
        response = requests.get(f'{API_BASE_URL}/health', timeout=2)
        return response.ok
    except:
        return False


def main():
    """Run all tests."""
    print()
    print("=" * 70)
    print(f"{Colors.BOLD}PSL SOCCER PREDICTOR API - COMPREHENSIVE TESTS{Colors.END}")
    print("=" * 70)
    print(f"API URL: {API_BASE_URL}")
    print(f"Test started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    # Check if API is available
    print(f"Checking API availability...")
    if not check_api_health():
        print_failure(f"API is not available at {API_BASE_URL}")
        print_info("Please ensure the backend server is running.")
        print_info("Start it with: python3 main.py")
        sys.exit(1)
    else:
        print_success("API is available")
    
    # Run tests
    test_email = test_registration()
    test_token = test_login(test_email) if test_email else None
    test_fixtures(test_token)
    test_predict()
    
    # Print summary
    results.summary()
    
    # Exit with appropriate code
    sys.exit(0 if results.failed == 0 else 1)


if __name__ == "__main__":
    main()

