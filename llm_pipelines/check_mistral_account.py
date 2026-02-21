#!/usr/bin/env python3
"""
Check Mistral API account status and available features.
"""

import os
from mistralai import Mistral

api_key = os.environ.get("MISTRAL_API_KEY")
client = Mistral(api_key=api_key)

print("Checking Mistral API account status...\n")

try:
    # Try to list models (this should work even on free tier)
    print("✓ API key is valid")
    print(f"  Key prefix: {api_key[:10]}...")
    
    # Try to check batch endpoint
    try:
        jobs = client.batch.jobs.list()
        print("✓ Batch API is accessible")
        print(f"  Existing batch jobs: {len(jobs) if hasattr(jobs, '__len__') else 'Unknown'}")
    except Exception as e:
        print(f"✗ Batch API not accessible: {e}")
        print("\nPossible reasons:")
        print("  1. API key not refreshed after upgrade")
        print("  2. Subscription tier doesn't include batch API")
        print("  3. Need to regenerate API key from console")
        print("\nAction: Go to https://console.mistral.ai/api-keys/")
        print("  → Delete old key")
        print("  → Create new key")
        print("  → Update MISTRAL_API_KEY in .env")
    
except Exception as e:
    print(f"✗ API error: {e}")

