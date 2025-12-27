# PSL Soccer Predictor API Tests

This directory contains comprehensive tests for the PSL Soccer Predictor API.

## Test File

- `test.py` - Comprehensive test suite covering:
  - User registration (with validation)
  - User login and authentication
  - Fixtures endpoint (authentication required)
  - Single match predictor (no authentication required)

## Running Tests

### Prerequisites

1. Ensure the backend server is running:
   ```bash
   python3 main.py
   ```

2. The API should be available at `http://localhost:8000`

### Run Tests

```bash
# From the project root directory
python3 tests/test.py
```

### Expected Output

The test script will:
- Check API availability
- Run all registration tests
- Run all login tests
- Run all fixtures endpoint tests
- Run single match predictor tests
- Display a summary with pass/fail counts

## Test Coverage

### 1. Registration Tests
- ✅ Valid user registration
- ✅ Duplicate email rejection
- ✅ Weak password validation
- ✅ Invalid email format validation

### 2. Login Tests
- ✅ Successful login with correct credentials
- ✅ Wrong password rejection
- ✅ Non-existent email rejection

### 3. Fixtures Endpoint Tests
- ✅ Authentication requirement (401 without token)
- ✅ Successful access with valid token
- ✅ Invalid token rejection

### 4. Single Match Predictor Tests
- ✅ No authentication required
- ✅ Prediction functionality

## Exit Codes

- `0` - All tests passed
- `1` - Some tests failed or API unavailable

## Notes

- Tests use randomly generated email addresses to avoid conflicts
- Tests are independent and can be run multiple times
- The test script will create test users in the database

