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
  
  # Send a structured task assignment
  python3 ntfy_messenger.py task "Research ATL weather patterns" --priority high
  
  # Request status report from worker
  python3 ntfy_messenger.py status
"""

import sys
import json
import time
import uuid
import requests
from datetime import datetime, timezone

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

def send_structured(msg_type: str, content: str, priority: str = "medium", task_id: str = None, metadata: dict = None):
    """
    Send a structured message with JSON metadata.
    
    msg_type: "task", "status_request", "message", "task_complete"
    priority: "high", "medium", "low"
    task_id: UUID (auto-generated if not provided)
    """
    if not task_id:
        task_id = str(uuid.uuid4())
    
    # Build metadata
    meta = {
        "type": msg_type,
        "id": task_id,
        "priority": priority,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }
    
    if metadata:
        meta.update(metadata)
    
    # Map priority to ntfy priority levels (1-5)
    ntfy_priority = {"high": 5, "medium": 3, "low": 1}.get(priority, 3)
    
    # Send message with metadata in header
    headers = {
        "Priority": str(ntfy_priority),
        "Tags": "drewops",
        "X-Metadata": json.dumps(meta)
    }
    
    full_msg = f"[DREWOPS] {content}\n\nMetadata: {json.dumps(meta, indent=2)}"
    
    resp = requests.post(BASE_URL, data=full_msg.encode("utf-8"), headers=headers)
    resp.raise_for_status()
    
    print(f"✅ Sent {msg_type} (ID: {task_id}, Priority: {priority})")
    return {"message_id": task_id, "response": resp.json()}

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
        print("Usage: ntfy_messenger.py [send|poll|listen|task|status] [args...]")
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
    
    elif action == "task":
        # Send structured task assignment
        if len(sys.argv) < 3:
            print("Usage: ntfy_messenger.py task \"task description\" [--priority high|medium|low]")
            sys.exit(1)
        
        task_desc = sys.argv[2]
        priority = "medium"
        
        # Parse optional --priority flag
        if len(sys.argv) > 3 and sys.argv[3] == "--priority" and len(sys.argv) > 4:
            priority = sys.argv[4].lower()
            if priority not in ["high", "medium", "low"]:
                print(f"Invalid priority: {priority}. Use high/medium/low")
                sys.exit(1)
        
        send_structured("task", task_desc, priority=priority)
    
    elif action == "status":
        # Request status report from worker
        send_structured("status_request", "Please send status update")
        print("📊 Status request sent")
    
    else:
        print(f"Unknown action: {action}")
        sys.exit(1)
