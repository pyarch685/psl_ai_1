#!/usr/bin/env python3
"""
Health check script for Railway deployment.

This script performs basic health checks on the application:
- Database connectivity
- Model loading
- API endpoint availability
"""
import os
import sys
import requests
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

def check_database():
    """Check database connectivity."""
    try:
        from db.engine import get_db_engine
        engine = get_db_engine()
        with engine.connect() as conn:
            conn.execute("SELECT 1")
        print("✓ Database connection: OK")
        return True
    except Exception as e:
        print(f"✗ Database connection: FAILED - {e}")
        return False


def check_model_storage():
    """Check model storage directory."""
    try:
        from core.model_store import get_model_directory
        model_dir = get_model_directory()
        if model_dir.exists():
            print(f"✓ Model storage directory: OK ({model_dir})")
            return True
        else:
            print(f"⚠ Model storage directory: NOT FOUND ({model_dir})")
            print("  This is OK if no model has been trained yet.")
            return True  # Not a failure, just a warning
    except Exception as e:
        print(f"✗ Model storage check: FAILED - {e}")
        return False


def check_api_endpoint(base_url: str = None):
    """Check API health endpoint."""
    if not base_url:
        base_url = os.getenv("API_URL", "http://localhost:8000")
    
    try:
        response = requests.get(f"{base_url}/health", timeout=5)
        if response.status_code == 200:
            print(f"✓ API health endpoint: OK ({base_url})")
            return True
        else:
            print(f"✗ API health endpoint: FAILED - Status {response.status_code}")
            return False
    except Exception as e:
        print(f"✗ API health endpoint: FAILED - {e}")
        return False


def check_environment_variables():
    """Check critical environment variables."""
    required = ["JWT_SECRET_KEY"]
    missing = []
    
    for var in required:
        value = os.getenv(var)
        if not value or value == "your-secret-key-change-in-production":
            missing.append(var)
    
    if missing:
        print(f"⚠ Missing environment variables: {', '.join(missing)}")
        return False
    
    print("✓ Environment variables: OK")
    return True


def main():
    """Run all health checks."""
    print("=" * 70)
    print("PSL AI - Health Check")
    print("=" * 70)
    print()
    
    results = []
    
    # Check environment
    results.append(("Environment Variables", check_environment_variables()))
    print()
    
    # Check database
    results.append(("Database", check_database()))
    print()
    
    # Check model storage
    results.append(("Model Storage", check_model_storage()))
    print()
    
    # Check API (optional, only if API_URL is set)
    api_url = os.getenv("API_URL")
    if api_url:
        results.append(("API Endpoint", check_api_endpoint(api_url)))
        print()
    
    # Summary
    print("=" * 70)
    print("Summary")
    print("=" * 70)
    
    all_passed = all(result[1] for result in results)
    
    for name, passed in results:
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"{status} - {name}")
    
    print()
    
    if all_passed:
        print("All checks passed!")
        sys.exit(0)
    else:
        print("Some checks failed. Please review the errors above.")
        sys.exit(1)


if __name__ == "__main__":
    main()

