#!/usr/bin/env python3
"""
Sanity Check for Google GenAI SDK Migration
"""

import os
import sys
from google import genai
from google.genai import types
from dotenv import load_dotenv

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

def main():
    load_dotenv()
    
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("❌ GEMINI_API_KEY not found in environment.")
        print("Please set it in .env or export it.")
        sys.exit(1)
        
    print(f"✅ Found GEMINI_API_KEY: {api_key[:4]}...{api_key[-4:]}")
    
    try:
        client = genai.Client(api_key=api_key)
        model_name = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")
        
        print(f"🔄 Testing connection to model: {model_name}...")
        
        response = client.models.generate_content(
            model=model_name,
            contents="Explain quantum computing in one short sentence.",
            config=types.GenerateContentConfig(
                temperature=0.7,
            )
        )
        
        print("\n✅ Verification Successful!")
        print(f"Output: {response.text}")
        
    except Exception as e:
        print(f"\n❌ Verification Failed: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()
