# Zellij Sessions for Alfred

List your Zellij sessions from Alfred, attach to one in your terminal, create a new one by name, or kill or delete one.

Running sessions are listed first, then exited ones that Zellij can resurrect. Each row has an icon for its state, so you can see at a glance whether ↩ attaches to a live session, brings back an exited one, or creates a new one.

## Usage

Type `zj` and part of a session name.

| Key | Action |
|---|---|
| ↩ | Attach to the session in your terminal (Alfred's Terminal setting). Exited sessions are resurrected. |
| ⌥ ↩ | Kill a running session, or delete an exited one |
| ⌘ C | Copy the session name |

The subtitle shows the state (current, running or EXITED) and how long ago the session was created.

If the name you type does not match a session exactly, the last row offers New session, which runs `zellij attach -c <name>`. With no sessions at all, ↩ starts a session with a name that Zellij picks. Names that start with `-` are refused, because Zellij would read them as an option.

⌥ ↩ runs `zellij kill-session` for a running session and `zellij delete-session` for an exited one, and shows the result as a notification.

## Configuration

There is nothing to configure.

## Requirements

- macOS with Alfred 5 and the Powerpack
- `/usr/bin/python3` (installed with the Xcode Command Line Tools)
- Zellij, tested with 0.45.1. Alfred does not use your shell's PATH, so the workflow uses the first `zellij` it finds in `/opt/homebrew/bin`, `/usr/local/bin`, `~/.cargo/bin` and `~/.local/bin`, in that order.
- Terminal actions use the app chosen in Alfred's Terminal setting (Terminal, iTerm or a custom script).

## Icons

Icons are drawn by `iconkit.js`, a small JavaScript for Automation script that uses AppKit, so there is nothing to install. The set is pre-rendered into `icons/`. After changing the icon table in `make_icons.py`, run `/usr/bin/python3 -B make_icons.py` to render it again.

| Icon | Meaning |
|---|---|
| Green terminal | Running session |
| Blue terminal | Session that Zellij marks as current |
| Grey moon | Exited session, can be resurrected |
| Blue plus | Create a new session |

## Install

Download the latest `.alfredworkflow` from Releases and open it.

To work on it, clone the repository and symlink it into Alfred's workflows folder:

```sh
git clone https://github.com/ndcorder/alfred-zellij-sessions.git
ln -s "$PWD/alfred-zellij-sessions" "<Alfred preferences>/Alfred.alfredpreferences/workflows/alfred-zellij-sessions"
```

## Development

```sh
/usr/bin/python3 -B -m unittest test_zj
```

Tests mock zellij, so they never list, attach to or kill your real sessions.

## Licence

MIT. See [LICENSE](LICENSE).
