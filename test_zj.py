"""Run: /usr/bin/python3 -B -m unittest test_zj  (from this folder). zellij is always mocked."""
import io
import json
import os
import plistlib
import subprocess
import sys
import unittest
from unittest import mock

import zj

# Real zellij 0.45.1 `list-sessions --no-formatting` output shapes.
LS = (
    "quiet-heron [Created 5months 18days 17h 29m 58s ago] (EXITED - attach to resurrect)\n"
    "work [Created 2h 3m 10s ago] (current)\n"
    "api-dev [Created 12m 5s ago] \n"
)


def setUpModule():
    # Tests must not depend on where, or whether, zellij is installed on this machine.
    p = mock.patch.object(zj, "ZELLIJ", "/opt/homebrew/bin/zellij")
    p.start()
    unittest.addModuleCleanup(p.stop)


def proc(stdout="", stderr="", rc=0):
    return subprocess.CompletedProcess([], rc, stdout, stderr)


class Base(unittest.TestCase):
    def items(self, query, ls=proc(LS)):
        with mock.patch.object(zj.subprocess, "run", return_value=ls) as run:
            out = zj.filter_items(query)
        self.run_mock = run
        return out


class Parsing(unittest.TestCase):
    def test_three_states(self):
        s = zj.parse_sessions(LS)
        self.assertEqual([(x["name"], x["state"]) for x in s],
                         [("quiet-heron", "exited"), ("work", "current"), ("api-dev", "active")])

    def test_age_keeps_two_largest_units(self):
        self.assertEqual(zj.parse_sessions(LS)[0]["age"], "5months 18days")

    def test_ansi_colours_are_ignored(self):
        # If a future zellij ignores --no-formatting, parsing must still work.
        s = zj.parse_sessions("\x1b[32;1mdev\x1b[m [Created \x1b[35;1m1m\x1b[m ago] \n")
        self.assertEqual(s[0]["name"], "dev")


class ScriptFilter(Base):
    def test_listing_is_read_only(self):
        self.items("")
        self.assertEqual(self.run_mock.call_args[0][0],
                         ["/opt/homebrew/bin/zellij", "list-sessions", "--no-formatting"])

    def test_running_sessions_listed_before_exited(self):
        self.assertEqual([i["title"] for i in self.items("")], ["work", "api-dev", "quiet-heron"])

    def test_enter_attaches_and_exited_says_resurrect(self):
        it = {i["title"]: i for i in self.items("")}
        self.assertEqual(it["api-dev"]["arg"], "/opt/homebrew/bin/zellij attach api-dev")
        self.assertIn("resurrect", it["quiet-heron"]["subtitle"])
        self.assertIn("EXITED", it["quiet-heron"]["subtitle"])

    def test_alt_passes_state_so_exited_gets_deleted(self):
        it = {i["title"]: i for i in self.items("")}
        self.assertEqual(it["quiet-heron"]["mods"]["alt"]["variables"], {"zj_state": "exited"})
        self.assertEqual(it["api-dev"]["mods"]["alt"]["variables"], {"zj_state": "active"})
        self.assertEqual(it["api-dev"]["mods"]["alt"]["arg"], "api-dev")

    def test_unknown_name_offers_create_with_c_flag(self):
        items = self.items("new thing")
        self.assertEqual(items[-1]["title"], "New session 'new thing'")
        # -c creates the session if missing; plain attach would fail.
        self.assertEqual(items[-1]["arg"], "/opt/homebrew/bin/zellij attach -c 'new thing'")
        self.assertFalse(items[-1]["mods"]["alt"]["valid"])

    def test_names_the_shell_or_zellij_would_misread(self):
        # zsh expands a bare =word; zellij reads a leading '-' as a flag.
        self.assertEqual(self.items("=x")[-1]["arg"], "/opt/homebrew/bin/zellij attach -c '=x'")
        bad = self.items("-x")[-1]
        self.assertFalse(bad["valid"])
        self.assertNotIn("arg", bad)

    def test_exact_name_does_not_offer_create(self):
        titles = [i["title"] for i in self.items("api-dev")]
        self.assertEqual(titles, ["api-dev"])

    def test_partial_name_shows_match_and_create(self):
        titles = [i["title"] for i in self.items("api")]
        self.assertEqual(titles, ["api-dev", "New session 'api'"])

    def test_no_sessions_offers_new_session(self):
        items = self.items("", ls=proc(stdout="No active zellij sessions found.\n", rc=1))
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["arg"], "/opt/homebrew/bin/zellij")
        items = self.items("dev", ls=proc(stderr="No active zellij sessions found.", rc=1))
        self.assertEqual(items[0]["title"], "New session 'dev'")

    def test_cli_error_is_shown_not_swallowed(self):
        items = self.items("", ls=proc(stderr="boom: socket broke", rc=2))
        self.assertEqual(items[0]["title"], "zellij list-sessions failed")
        self.assertFalse(items[0]["valid"])

    def test_timeout_gives_item(self):
        with mock.patch.object(zj.subprocess, "run", side_effect=subprocess.TimeoutExpired("z", 5)):
            items = zj.filter_items("")
        self.assertIn("timed out", items[0]["title"])

    def test_missing_zellij_says_where_it_looked(self):
        with mock.patch.object(zj, "ZELLIJ", None), mock.patch.object(zj.subprocess, "run") as run:
            items = zj.filter_items("x")
        run.assert_not_called()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["title"], "zellij not found")
        self.assertIn("Looked in /opt/homebrew/bin, /usr/local/bin, ~/.cargo/bin, ~/.local/bin",
                      items[0]["subtitle"])
        self.assertFalse(items[0]["valid"])


class Discovery(unittest.TestCase):
    """Alfred's PATH has none of these folders, so the workflow searches them itself."""

    HOME = os.path.expanduser("~")
    ORDER = ["/opt/homebrew/bin/zellij", "/usr/local/bin/zellij",
             HOME + "/.cargo/bin/zellij", HOME + "/.local/bin/zellij"]

    def find(self, files, executable):
        with mock.patch.object(zj.os.path, "isfile", side_effect=lambda p: p in files), \
                mock.patch.object(zj.os, "access", side_effect=lambda p, mode: p in executable):
            return zj.find_zellij()

    def test_first_executable_in_search_order_wins(self):
        # Apple silicon Homebrew, Intel Homebrew, cargo install, ~/.local/bin.
        for i, path in enumerate(self.ORDER):
            later = set(self.ORDER[i:])
            self.assertEqual(self.find(later, later), path)

    def test_non_executable_file_is_skipped(self):
        everything = set(self.ORDER)
        self.assertEqual(self.find(everything, {self.ORDER[2]}), self.ORDER[2])

    def test_nothing_found(self):
        self.assertIsNone(self.find(set(), set()))


class Remove(unittest.TestCase):
    def call(self, state, name, result=proc()):
        with mock.patch.object(zj.subprocess, "run", return_value=result) as run:
            msg = zj.remove(state, name)
        return msg, run.call_args[0][0]

    def test_exited_session_is_deleted(self):
        # kill-session does nothing for a dead session; delete removes its resurrection data.
        msg, argv = self.call("exited", "old")
        self.assertEqual(argv, ["/opt/homebrew/bin/zellij", "delete-session", "old"])
        self.assertEqual(msg, "Deleted 'old'")

    def test_running_session_is_killed_not_deleted(self):
        for state in ("active", "current", ""):
            _, argv = self.call(state, "live")
            self.assertEqual(argv, ["/opt/homebrew/bin/zellij", "kill-session", "live"], state)

    def test_failure_reported_in_notification(self):
        msg, _ = self.call("exited", "x", proc(stderr='Session: "x" not found.', rc=2))
        self.assertEqual(msg, 'Failed to delete-session \'x\': Session: "x" not found.')


class Icons(Base):
    """The icon must say at a glance whether ↩ attaches to something live, resurrects a dead
    session, or creates a new one; problems must never look like sessions."""

    HERE = os.path.dirname(os.path.abspath(__file__))

    def icon_of(self, items, title):
        return next(i for i in items if i["title"] == title)["icon"]["path"]

    def test_each_session_state_gets_its_own_icon(self):
        items = self.items("")
        self.assertEqual(self.icon_of(items, "api-dev"), "icons/running.png")
        self.assertEqual(self.icon_of(items, "work"), "icons/current.png")
        self.assertEqual(self.icon_of(items, "quiet-heron"), "icons/exited.png")

    def test_new_session_and_empty_list_use_the_create_icon(self):
        self.assertEqual(self.items("brand-new")[-1]["icon"]["path"], "icons/new.png")
        empty = self.items("", ls=proc(stdout="No active zellij sessions found.\n", rc=1))
        self.assertEqual(empty[0]["icon"]["path"], "icons/new.png")  # ↩ starts a session

    def test_problems_use_the_shared_message_icons(self):
        self.assertEqual(self.items("-x")[-1]["icon"]["path"], "icons/warning.png")
        self.assertEqual(self.items("", ls=proc(stderr="boom", rc=2))[0]["icon"]["path"], "icons/error.png")
        with mock.patch.object(zj.subprocess, "run", side_effect=subprocess.TimeoutExpired("z", 5)):
            self.assertEqual(zj.filter_items("")[0]["icon"]["path"], "icons/warning.png")
        with mock.patch.object(zj, "ZELLIJ", None):
            self.assertEqual(zj.filter_items("")[0]["icon"]["path"], "icons/error.png")
        out = io.StringIO()
        with mock.patch.object(zj, "filter_items", side_effect=RuntimeError("x")), \
                mock.patch.object(sys, "argv", ["zj.py", "q"]), mock.patch.object(sys, "stdout", out):
            zj.main()
        self.assertEqual(json.loads(out.getvalue())["items"][0]["icon"]["path"], "icons/error.png")

    def test_every_item_has_an_icon_that_make_icons_renders_and_that_exists(self):
        # A typo in a name, or a forgotten make_icons run, shows Alfred's blank default icon.
        import make_icons
        cases = [self.items(""), self.items("new"), self.items("-x"),
                 self.items("", ls=proc(stderr="boom", rc=2)),
                 self.items("", ls=proc(stdout="No active zellij sessions found.\n", rc=1))]
        used = {i["icon"]["path"] for items in cases for i in items}
        used |= {"icons/%s.png" % n for n in zj.STATE_ICONS.values()}
        for path in used:
            name = os.path.basename(path)[:-len(".png")]
            self.assertIn(name, make_icons.JOBS, path)
            self.assertTrue(os.path.isfile(os.path.join(self.HERE, path)), path)


class Wiring(unittest.TestCase):
    def test_emitted_mods_match_plist_connections(self):
        # A mod without a plist connection does nothing in Alfred; keep them in sync.
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "info.plist"), "rb") as f:
            wf = plistlib.load(f)
        sf = [o["uid"] for o in wf["objects"] if o["type"] == "alfred.workflow.input.scriptfilter"][0]
        masks = {c["modifiers"] for c in wf["connections"][sf]}
        self.assertEqual(masks, {0, 524288})  # ↩ attach, ⌥↩ remove
        script = [o for o in wf["objects"] if o["type"] == "alfred.workflow.action.script"][0]
        self.assertIn('remove "$zj_state" "$1"', script["config"]["script"])

    def test_main_prints_valid_json_on_unexpected_error(self):
        out = io.StringIO()
        with mock.patch.object(zj, "filter_items", side_effect=RuntimeError("x")), \
                mock.patch.object(sys, "argv", ["zj.py", "q"]), mock.patch.object(sys, "stdout", out):
            zj.main()
        self.assertEqual(json.loads(out.getvalue())["items"][0]["title"], "zj failed")


if __name__ == "__main__":
    unittest.main()
