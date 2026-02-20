#!/usr/bin/env python3
"""
Mistral CLI — Quick access to Mistral AI for research, trade analysis, and forecasts.

Usage:
  python3 mistral_cli.py ask "What's the latest on AI regulation?"
  python3 mistral_cli.py analyze-trade AAPL
  python3 mistral_cli.py forecast "New York"
"""

import sys
import os
import json
import requests
from pathlib import Path

# Load API key from .secrets.env
SECRETS_FILE = Path.home() / ".secrets.env"
API_KEY = None

def load_api_key():
    """Load MISTRAL_API_KEY from /root/.secrets.env"""
    global API_KEY
    if SECRETS_FILE.exists():
        with open(SECRETS_FILE) as f:
            for line in f:
                if line.startswith("MISTRAL_API_KEY="):
                    API_KEY = line.split("=", 1)[1].strip().strip('"').strip("'")
                    return
    # Fallback to hardcoded key if not in file
    API_KEY = "8auQZO2jWHMQYR9lIjRo3eoiPMpgiBSg"

def ask_mistral(prompt: str, system_prompt: str = None) -> str:
    """Send a query to Mistral AI and return the response."""
    if not API_KEY:
        load_api_key()
    
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})
    
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": "mistral-large-latest",
        "messages": messages,
        "temperature": 0.7
    }
    
    try:
        resp = requests.post(
            "https://api.mistral.ai/v1/chat/completions",
            headers=headers,
            json=payload,
            timeout=30
        )
        resp.raise_for_status()
        result = resp.json()
        return result["choices"][0]["message"]["content"]
    except Exception as e:
        return f"Error: {str(e)}"

def cmd_ask(question: str):
    """General research query."""
    print("🤔 Asking Mistral...")
    response = ask_mistral(question)
    print(f"\n{response}\n")

def cmd_analyze_trade(ticker: str):
    """Get a second opinion on a trade."""
    system_prompt = (
        "You are a financial analyst providing quick trade analysis. "
        "Consider market conditions, recent news, technical levels, and risk factors. "
        "Be concise but thorough."
    )
    
    prompt = (
        f"Analyze {ticker.upper()} for a potential trade. "
        f"What are the key factors to consider right now? "
        f"What are the risks and opportunities?"
    )
    
    print(f"📊 Analyzing {ticker.upper()}...")
    response = ask_mistral(prompt, system_prompt)
    print(f"\n{response}\n")

def cmd_forecast(city: str):
    """Cross-check weather forecasts."""
    system_prompt = (
        "You are a meteorology assistant. Provide current weather insights and "
        "short-term forecast analysis. Be specific about timing and conditions."
    )
    
    prompt = (
        f"What's the current weather situation and short-term forecast for {city}? "
        f"Any notable weather patterns or events to watch?"
    )
    
    print(f"🌤️  Checking forecast for {city}...")
    response = ask_mistral(prompt, system_prompt)
    print(f"\n{response}\n")

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    
    command = sys.argv[1]
    
    if command == "ask":
        if len(sys.argv) < 3:
            print("Usage: mistral_cli.py ask \"your question\"")
            sys.exit(1)
        cmd_ask(sys.argv[2])
    
    elif command == "analyze-trade":
        if len(sys.argv) < 3:
            print("Usage: mistral_cli.py analyze-trade TICKER")
            sys.exit(1)
        cmd_analyze_trade(sys.argv[2])
    
    elif command == "forecast":
        if len(sys.argv) < 3:
            print("Usage: mistral_cli.py forecast CITY")
            sys.exit(1)
        cmd_forecast(sys.argv[2])
    
    else:
        print(f"Unknown command: {command}")
        print(__doc__)
        sys.exit(1)

if __name__ == "__main__":
    main()
