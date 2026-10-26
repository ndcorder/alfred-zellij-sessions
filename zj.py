#!/usr/bin/env python3
"""Alfred Script Filter for Zellij sessions: attach, create, kill or delete.

  zj.py "<query>"                 Script Filter JSON
  zj.py remove <state> <name>     kill-session (running) or delete-session (exited); prints a notification line
"""
import json
import os
import re
import shlex
import subprocess
import sys

# Alfred's PATH has none of these, so look in each install location; the first executable wins:
# Homebrew (Apple silicon, then Intel), cargo install, then other per-user installs.
ZELLIJ_DIRS = ("/opt/homebrew/bin", "/usr/local/bin", "~/.cargo/bin", "~/.local/bin")
TIMEOUT = 5
ANSI = re.compile(r"\x1b\[[0-9;]*m")
# "name [Created 5months 18days 17h 29m 58s ago] (EXITED - attach to resurrect)"
LINE = re.compile(r"^(?P<name>.+?) \[Created (?P<age>.+?) ago\](?: \((?P<tag>[^)]*)\))?\s*$")
# Session state -> pre-rendered icon (make_icons.py). "active" = running, not attached here.
STATE_ICONS = {"active": "running", "current": "current", "exited": "exited"}


def find_zellij():
    for d in ZELLIJ_DIRS:
        path = os.path.join(os.path.expanduser(d), "zellij")
        if os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    return None


ZELLIJ = find_zellij()  # once per run: Alfred starts the script fresh for every query


def icon(name):
    """Static icon from icons/ (see make_icons.py); Alfred resolves the path from the workflow folder."""
    return {"path": "icons/%s.png" % name}


def run(args):
    return subprocess.run([ZELLIJ] + args, capture_output=True, text=True, timeout=TIMEOUT,
                          stdin=subprocess.DEVNULL)


def parse_sessions(output):
    sessions = []
    for raw in output.splitlines():
        line = ANSI.sub("", raw).strip()
        m = LINE.match(line)
        if not m:
            continue
        tag = (m.group("tag") or "").lower()
        state = "exited" if "exited" in tag else "current" if tag == "current" else "active"
        sessions.append({"name": m.group("name"), "age": short_age(m.group("age")), "state": state})
    return sessions


def short_age(age):
    """'5months 18days 17h 29m 58s' -> '5months 18days' (two largest units)."""
    return " ".join(age.split()[:2])


def list_sessions():
    """Return (sessions, error_item_or_None)."""
    if not ZELLIJ:
        return [], {"title": "zellij not found",
                    "subtitle": "Looked in %s · brew install zellij" % ", ".join(ZELLIJ_DIRS),
                    "valid": False, "icon": icon("error")}
    try:
        p = run(["list-sessions", "--no-formatting"])
    except subprocess.TimeoutExpired:
        return [], {"title": "zellij list-sessions timed out", "subtitle": "Took over %ds" % TIMEOUT, "valid": False,
                    "icon": icon("warning")}
    except OSError as e:
        return [], {"title": "Could not run zellij", "subtitle": str(e), "valid": False, "icon": icon("error")}
    sessions = parse_sessions(p.stdout)
    if p.returncode != 0 and not sessions:
        msg = ANSI.sub("", (p.stderr or p.stdout or "").strip())
        if "no active zellij sessions" in msg.lower() or not msg:
            return [], None  # zellij exits 1 when there are no sessions
        return [], {"title": "zellij list-sessions failed", "subtitle": msg.splitlines()[0], "valid": False,
                    "icon": icon("error")}
    return sessions, None


def attach_cmd(name, create=False):
    quoted = shlex.quote(name)
    if quoted.startswith("="):  # shlex leaves it bare, but zsh expands =word to a command path
        quoted = "'%s'" % name
    return "%s attach %s%s" % (ZELLIJ, "-c " if create else "", quoted)


def session_item(s):
    label = {"current": "current", "active": "running", "exited": "EXITED"}[s["state"]]
    verb = "resurrect" if s["state"] == "exited" else "attach"
    remove = "delete" if s["state"] == "exited" else "kill"
    return {
        "uid": "zj-" + s["name"],
        "title": s["name"],
        "icon": icon(STATE_ICONS[s["state"]]),
        "subtitle": "%s · created %s ago · ↩ %s" % (label, s["age"], verb),
        "arg": attach_cmd(s["name"]),
        "autocomplete": s["name"],
        "text": {"copy": s["name"], "largetype": s["name"]},
        "mods": {
            "alt": {"arg": s["name"], "variables": {"zj_state": s["state"]},
                    "subtitle": "%s session '%s'" % ("Delete" if remove == "delete" else "Kill", s["name"])},
        },
    }


def new_item(name):
    return {
        "title": "New session '%s'" % name,
        "icon": icon("new"),
        "subtitle": "Create and attach in iTerm",
        "arg": attach_cmd(name, create=True),
        "autocomplete": name,
        "mods": {"alt": {"valid": False, "subtitle": "Session does not exist yet"}},
    }


def filter_items(query):
    sessions, error = list_sessions()
    if error:
        return [error]
    q = query.strip()
    hits = [s for s in sessions if q.lower() in s["name"].lower()]
    order = {"current": 0, "active": 1, "exited": 2}
    hits.sort(key=lambda s: (order[s["state"]], s["name"]))
    items = [session_item(s) for s in hits]
    if q and not any(s["name"] == q for s in sessions):
        if q.startswith("-"):  # zellij would parse it as a flag
            items.append({"title": "Session names cannot start with '-'", "valid": False,
                          "icon": icon("warning")})
        else:
            items.append(new_item(q))
    if not q and not sessions:
        items.append({
            "title": "No zellij sessions",
            "icon": icon("new"),  # ↩ starts one, so it reads as an action, not a dead end
            "subtitle": "↩ start an auto-named session · or type a name to create one",
            "arg": ZELLIJ,
            "mods": {"alt": {"valid": False, "subtitle": "Nothing to remove"}},
        })
    return items


def remove(state, name):
    """Kill a running session or delete an exited one. Returns the notification text."""
    sub = "delete-session" if state == "exited" else "kill-session"
    if not ZELLIJ:
        return "Failed to %s '%s': zellij not found" % (sub, name)
    try:
        p = run([sub, name])
    except (OSError, subprocess.TimeoutExpired) as e:
        return "Failed to %s '%s': %s" % (sub, name, e)
    if p.returncode != 0:
        msg = ANSI.sub("", (p.stderr or p.stdout or "").strip()) or "exit %d" % p.returncode
        return "Failed to %s '%s': %s" % (sub, name, msg.splitlines()[0])
    return "%s '%s'" % ("Deleted" if sub == "delete-session" else "Killed", name)


def main():
    if len(sys.argv) == 4 and sys.argv[1] == "remove":
        sys.stdout.write(remove(sys.argv[2], sys.argv[3]))
        return
    query = sys.argv[1] if len(sys.argv) > 1 else ""
    try:
        items = filter_items(query)
    except Exception as e:  # always hand Alfred valid JSON
        items = [{"title": "zj failed", "subtitle": "%s: %s" % (type(e).__name__, e), "valid": False,
                  "icon": icon("error")}]
    json.dump({"items": items}, sys.stdout)


if __name__ == "__main__":
    main()
