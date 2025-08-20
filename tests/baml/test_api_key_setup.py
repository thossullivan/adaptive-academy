#!/usr/bin/env python3
"""
Test API Key Configuration
Simple test to verify that the ANTHROPIC_API_KEY is properly loaded from .env file.
"""

import os
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

def load_env_file():
    """Load environment variables from .env file."""
    env_file = project_root / ".env"

    if not env_file.exists():
        print(f"❌ .env file not found at: {env_file}")
        return False

    print(f"✅ Found .env file at: {env_file}")

    # Read .env file manually
    env_vars = {}
    try:
        with open(env_file, 'r') as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    key = key.strip()
                    value = value.strip().strip('"').strip("'")
                    env_vars[key] = value
                    # Set in os.environ for current session
                    os.environ[key] = value
    except Exception as e:
        print(f"❌ Error reading .env file: {e}")
        return False

    print(f"✅ Loaded {len(env_vars)} environment variables from .env")
    return True

def test_api_keys():
    """Test API key availability."""
    print("\n🔑 Testing API Key Configuration")
    print("=" * 40)

    # Load .env file first
    load_env_file()

    # Check for API keys
    api_keys = {
        'ANTHROPIC_API_KEY': os.getenv('ANTHROPIC_API_KEY'),
        'OPENAI_API_KEY': os.getenv('OPENAI_API_KEY'),
        'GOOGLE_API_KEY': os.getenv('GOOGLE_API_KEY')
    }

    found_keys = []
    for key, value in api_keys.items():
        if value:
            # Show first 8 and last 4 characters for security
            masked_value = f"{value[:8]}...{value[-4:]}" if len(value) > 12 else "***"
            print(f"✅ {key}: {masked_value}")
            found_keys.append(key)
        else:
            print(f"❌ {key}: Not found")

    if found_keys:
        print(f"\n✅ Found {len(found_keys)} API key(s): {found_keys}")
        return True
    else:
        print(f"\n❌ No API keys found!")
        print("\nMake sure your .env file contains:")
        print("ANTHROPIC_API_KEY=your_key_here")
        return False

async def test_baml_with_api_key():
    """Test BAML functionality with API key."""
    print("\n🧪 Testing BAML with API Key")
    print("=" * 40)

    try:
        from baml_client import b
        print("✅ BAML client imported successfully")

        # Simple test call
        print("📋 Testing GenerateProjectPlan...")

        result = await b.GenerateProjectPlan(
            task_description="Create a simple hello world app",
            working_directory=".",
            existing_tech_stack=["JavaScript"]
        )

        print("✅ BAML API call successful!")
        print(f"📊 Generated {len(result.phases)} phases")
        print(f"📝 Project summary: {result.project_summary[:100]}...")

        return True

    except Exception as e:
        error_msg = str(e)
        if "authentication_error" in error_msg or "invalid x-api-key" in error_msg:
            print("❌ Authentication failed - API key is invalid or not properly loaded")
            print("🔍 Check that your ANTHROPIC_API_KEY in .env is correct")
        elif "BamlClientHttpError" in error_msg:
            print(f"❌ BAML API error: {error_msg}")
        else:
            print(f"❌ Unexpected error: {error_msg}")

        return False

def main():
    """Main test function."""
    print("🔍 API Key Configuration Test")
    print("=" * 50)

    # Test 1: Check API key loading
    keys_loaded = test_api_keys()

    if not keys_loaded:
        print("\n⚠️ Cannot proceed without API keys")
        return

    # Test 2: Test BAML functionality
    import asyncio
    success = asyncio.run(test_baml_with_api_key())

    # Summary
    print("\n📋 Test Summary:")
    print(f"  API Keys Loaded: {'✅ PASS' if keys_loaded else '❌ FAIL'}")
    print(f"  BAML Functionality: {'✅ PASS' if success else '❌ FAIL'}")

    if keys_loaded and success:
        print("\n🎉 All tests passed! Your API key is working correctly.")
        print("You can now run the full BAML test suite:")
        print("  python -m pytest tests/baml/ -v")
    else:
        print("\n⚠️ Some tests failed. Please check your .env file configuration.")

if __name__ == "__main__":
    main()
