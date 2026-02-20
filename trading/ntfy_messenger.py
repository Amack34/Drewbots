#!/usr/bin/env python3
"""
ntfy.sh messenger — dead simple bot-to-bot communication.
No accounts, no browser, just HTTP.

Usage:
  # Send a message
  python3 ntfy_messenger.py send "Hello from DrewOps"
  
  # Poll for new messages (last 10 min)
  python3 ntfy_messenger.py poll
  
  # Listen for messages in real-time (blocking)
  python3 ntfy_messenger.py listen
"""

import sys
import json
import time
import requests
from datetime import datetime

# Private topic — UUID-based so nobody guesses it
TOPIC = "drewops-8e735236-5152-435b-82d7-e20d0b0593de"
BASE_URL = f"https://ntfy.sh/{TOPIC}"

def send(message: str, title: str = None, priority: int = 3, sender: str = "drewops"):
    """Send a message to the shared channel."""
    headers = {"Priority": str(priority)}
    if title:
        headers["Title"] = title
    headers["Tags"] = sender
    
    # Prefix with sender name for clarity
    full_msg = f"[{sender.upper()}] {message}"
    
    resp = requests.post(BASE_URL, data=full_msg.encode("utf-8"), headers=headers)
    resp.raise_for_status()
    return resp.json()

def poll(since: str = "10m", sender_filter: str = None):
    """Poll for recent messages."""
    resp = requests.get(f"{BASE_URL}/json?poll=1&since={since}")
    resp.raise_for_status()
    
    messages = []
    for line in resp.text.strip().split("\n"):
        if not line:
            continue
        msg = json.loads(line)
        if msg.get("event") == "message":
            if sender_filter and sender_filter not in msg.get("tags", []):
                continue
            messages.append({
                "time": datetime.fromtimestamp(msg["time"]).strftime("%Y-%m-%d %H:%M:%S"),
                "message": msg.get("message", ""),
                "title": msg.get("title", ""),
                "tags": msg.get("tags", []),
            })
    return messages

def listen():
    """Listen for messages in real-time (blocking)."""
    resp = requests.get(f"{BASE_URL}/json", stream=True, timeout=None)
    for line in resp.iter_lines():
        if not line:
            continue
        msg = json.loads(line)
        if msg.get("event") == "message":
            ts = datetime.fromtimestamp(msg["time"]).strftime("%H:%M:%S")
            print(f"[{ts}] {msg.get('message', '')}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: ntfy_messenger.py [send|poll|listen] [args...]")
        sys.exit(1)
    
    action = sys.argv[1]
    
    if action == "send":
        msg = sys.argv[2] if len(sys.argv) > 2 else "ping"
        sender = sys.argv[3] if len(sys.argv) > 3 else "drewops"
        result = send(msg, sender=sender)
        print(f"Sent: {msg}")
    
    elif action == "poll":
        since = sys.argv[2] if len(sys.argv) > 2 else "10m"
        msgs = poll(since=since)
        if msgs:
            for m in msgs:
                print(f"[{m['time']}] {m['message']}")
        else:
            print("No messages")
    
    elif action == "listen":
        print(f"Listening on {TOPIC}...")
        listen()
    
    else:
        print(f"Unknown action: {action}")
        sys.exit(1)
