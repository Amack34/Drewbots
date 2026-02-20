# Worker Task Protocol

**Version:** 1.0  
**Last Updated:** 2026-02-20

This document defines the structured communication protocol for task assignment and coordination between DrewOps (manager) and Worker (executor) via ntfy.sh.

---

## Overview

DrewOps and Worker communicate asynchronously via ntfy.sh using a structured message format with JSON metadata. This enables:

- **Task assignment** with priority levels
- **Status tracking** and progress reports
- **Async coordination** across devices/locations
- **Clear audit trail** of all assignments and completions

---

## Message Types

All structured messages include JSON metadata with these fields:

```json
{
  "type": "task|status_request|message|task_complete",
  "id": "uuid",
  "priority": "high|medium|low",
  "timestamp": "ISO-8601-timestamp"
}
```

### 1. `task` — Task Assignment

**Sent by:** DrewOps  
**Purpose:** Assign a discrete task to Worker

**Command:**
```bash
python3 ntfy_messenger.py task "Research ATL weather patterns for next 48h" --priority high
```

**Metadata:**
```json
{
  "type": "task",
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "priority": "high",
  "timestamp": "2026-02-20T13:00:00Z"
}
```

**Worker Response Format:**
```json
{
  "type": "task_complete",
  "task_id": "550e8400-e29b-41d4-a716-446655440000",
  "result": "Analysis complete. Created weather-patterns-atl.md in research/",
  "timestamp": "2026-02-20T14:30:00Z"
}
```

---

### 2. `status_request` — Status Check

**Sent by:** DrewOps  
**Purpose:** Request current status from Worker

**Command:**
```bash
python3 ntfy_messenger.py status
```

**Worker Response:** Summary of current tasks, progress, blockers

---

### 3. `message` — General Communication

**Sent by:** Either party  
**Purpose:** Unstructured updates, questions, or notifications

**Command:**
```bash
python3 ntfy_messenger.py send "Weather data pipeline running normally"
```

---

## Priority Levels & SLAs

| Priority | Response Time | Use Cases |
|----------|---------------|-----------|
| **high** | < 1 hour | Urgent blockers, time-sensitive research, critical bugs |
| **medium** | < 4 hours | Regular research tasks, code reviews, analysis |
| **low** | < 24 hours | Documentation, refactoring, exploratory work |

**Note:** SLAs apply during Worker's active hours (typically 9am-9pm ET). Overnight tasks queue for next morning.

---

## Daily Workflow

### Morning Assignment (8:00 AM ET)
1. DrewOps reviews priorities and market conditions
2. Sends 1-3 structured tasks via `ntfy_messenger.py task`
3. Worker receives tasks and confirms receipt
4. Worker begins work, creates feature branch if needed

### Midday Check-in (12:00 PM ET)
1. DrewOps sends `status` request
2. Worker reports progress, flags blockers
3. Adjust priorities if needed

### Evening Deliverable Review (6:00 PM ET)
1. Worker completes tasks, pushes to GitHub
2. Sends `task_complete` responses with results summary
3. DrewOps reviews code/research, provides feedback
4. Planning for next day begins

---

## GitHub Workflow

### Worker Side
1. Receive task via ntfy
2. Create feature branch: `git checkout -b task/BRIEF-DESCRIPTION`
3. Complete work (code, tests, docs)
4. Commit with descriptive message: `git commit -m "Add weather validation for ATL-B79.5"`
5. Push to remote: `git push origin task/BRIEF-DESCRIPTION`
6. Notify DrewOps via ntfy with `task_complete` message

### DrewOps Review
1. Receive `task_complete` notification
2. Review changes: `git fetch && git checkout task/BRIEF-DESCRIPTION`
3. Run tests, validate quality
4. Either:
   - **Merge:** `git checkout main && git merge task/BRIEF-DESCRIPTION && git push`
   - **Request changes:** Send feedback via ntfy with specific revisions needed
5. Delete branch after merge: `git branch -d task/BRIEF-DESCRIPTION`

---

## Escalation Paths

### Worker Offline (No Response After SLA)
1. DrewOps checks Worker's last-seen timestamp
2. If > 6 hours without response:
   - Mark task as `BLOCKED - Worker Offline`
   - Proceed with alternative plan (do it yourself or defer)
3. Log downtime for reliability tracking

### Task Blocked (Worker Can't Complete)
1. Worker sends message: `"BLOCKED: Task XYZ blocked by [reason]"`
2. DrewOps provides guidance or reprioritizes
3. If still blocked, reassign or defer

### Urgent Override
1. DrewOps sends task with `--priority high` and "URGENT:" prefix
2. Worker interrupts current work if safe to do so
3. Acknowledges receipt within 15 minutes

---

## Backward Compatibility

The updated `ntfy_messenger.py` maintains full backward compatibility:

- `send` and `poll` commands work exactly as before
- Existing cron jobs and scripts unaffected
- Structured protocol is opt-in via `task` and `status` commands

---

## Example Session

```bash
# Morning assignment
$ python3 ntfy_messenger.py task "Validate METAR sources for ORD market" --priority high
✅ Sent task (ID: abc-123, Priority: high)

# Worker receives and starts work...

# Midday check-in
$ python3 ntfy_messenger.py status
📊 Status request sent

# Worker responds via ntfy...

# Evening completion
# Worker sends: task_complete with result summary
```

---

## Future Enhancements

- **Task queuing system** with persistent state
- **Automated testing triggers** on task completion
- **Performance metrics** (avg completion time by priority)
- **Multi-worker support** with load balancing

---

**Last Review:** 2026-02-20  
**Owner:** DrewOps  
**Status:** Active
