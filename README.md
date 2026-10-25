# Monoqueue

[![License](https://img.shields.io/pypi/l/monoqueue.svg)](https://github.com/ctrueden/monoqueue/raw/main/UNLICENSE)
[![PyPI](https://img.shields.io/pypi/v/monoqueue.svg)](https://pypi.org/project/monoqueue)
[![Python Version](https://img.shields.io/pypi/pyversions/monoqueue.svg)](https://python.org)

*Fight burnout. Stay organized.*

## Purpose

This project unifies your support queue across various sources, such as:

* GitHub issues and PRs
* Topics from online forums
* Tickets from helpdesk software
* Any action that can be represented by a URL

Monoqueue's target audience is people managing large numbers of action items:

* Maintainers of open source software projects
* Support personnel on public community forums
* Anyone with more action items than they can finish

Items in the queue are scored according to a customizable ruleset, so that
you can attack them in order, maximizing the impact of your time and effort,
while minimizing decision paralysis and fatigue from repeated evaluation of
which items to address next.

It is designed to scale as your list of items becomes more than one person can
possibly handle completely. Rather than succumbing to Sisyphean ennui, define
your scoring criteria, let monoqueue sort your items, and do what you can!

You're only human; use monoqueue to be your best within a limited time budget.

## Design goals

* Efficient
* [Choice-minimal](https://tim.blog/2008/02/06/the-choice-minimal-lifestyle-6-formulas-for-more-output-and-less-overwhelm/)
* Impact maximizing
* [Open source](UNLICENSE)
* Scriptable

## Installation

It is recommended to install Python-based tools like monoqueue using
[uv](https://docs.astral.sh/uv/):

```shell
uv tool install monoqueue
```

Or from source:

```shell
git clone https://github.com/ctrueden/monoqueue
uv tool install --reinstall-package monoqueue --with-editable monoqueue monoqueue
```

## Configuration

Monoqueue reads three files in `~/.config/monoqueue/`:

* `rules.conf`: the [rules](#rules) scoring your action items.
* `sources.conf`: the [sources](#sources) of your action items, with their
  API keys and passwords, so keep it private.
* `settings.conf`: everything else, e.g. for [agents](#agents).

Rules and settings hold no secrets, so you can share them, e.g. among
your dotfiles. (Older versions of monoqueue used one file,
`~/.config/monoqueue.conf`; run `mq migrate-config` to split it up.)

```shell
mkdir -p ~/.config/monoqueue
vi ~/.config/monoqueue/rules.conf
```

Each section of `rules.conf` is a group of rules, and each entry a rule,
named however you like:

```ini
# Things I flagged myself.
[commitments]
bookmark = bookmark                                   -> +20: action bookmark

[github]
pr            = issue/pull_request                    -> +20: pull request
assigned      = "ctrueden" in issue/assignees/login   -> +5: assigned to me
assigned-only = ["ctrueden"] == issue/assignees/login -> +5: assigned to only me
monoqueue     = "/monoqueue/" in issue/url            -> +5: favorite project (monoqueue)
next-release  = issue/milestone/title == "next-release" -> +3: next-release milestone
mention       = "@ctrueden" in issue/body             -> +2: mentions me
contributor   = issue/author_association == "CONTRIBUTOR" -> +5: issue author is non-member
open          = issue/state == "open"                 -> +1: open issue
reactions     = (10 if issue/reactions/total_count > 10 else issue/reactions/total_count) -> +X: reactions
comments      = (5 if issue/comments > 20 else issue/comments / 4) -> +X: comments

[forum]
unanswered    = topic/has_accepted_answer is False    -> +5: has no accepted answer
monoqueue-tag = "monoqueue" in topic/tags             -> +5: monoqueue tag

# Rapid response: +40 when brand new, halving after 12 hours, then fading.
[freshness]
updated = (1728000 / (seconds_since_update + 43200) if seconds_since_update < 2592000 else 0) -> +X: fresh activity

# Multipliers last, so they scale the total.
[multipliers]
draft       = issue/draft                             -> /2: draft PR
unscheduled = issue/milestone/title == "unscheduled"  -> /100: unscheduled milestone
```

Each section of `sources.conf` is a source, whose kind (its `handler`)
defaults to the section's name:

```ini
[bookmarks]
folder = ACTION

[github]
token = <your-github-api-token>
query = is:open+org:my-favorite-org+org:my-other-favorite-org+repo:a-repo-I-manage

[tabs]
exclude =
  ^https://mail\.google\.com/
  ^https://calendar\.google\.com/

[scijava-team]
dev_id = <your-scijava-developer-id>

[forum.example.com]
handler = discourse
username = <your-discourse-username-on-forum.example.com>
key = <discourse-api-key-for-forum.example.com>
query = #a-category-to-search tags:foo,bar,stuff status:open status:unsolved
```

Then protect your secrets:

```shell
chmod 600 ~/.config/monoqueue/sources.conf
```

A `#` after whitespace begins a comment, anywhere on a line.

### Rules

Rules are written in Python syntax, parsed by Python's `ast` module, and evaluated
using a custom evaluator to avoid calling the insecure `eval` function. The monoqueue
evaluator supports standard Python unary and binary operators, as well as a special
overload of the divide (`/`) operator for digging into nested data structures easily.
Conditional expressions work too, e.g. to cap a value:

```ini
comments = (5 if issue/comments > 20 else issue/comments / 4) -> +X: comments
```

Rules run in file order, each adding to (or subtracting from, multiplying,
or dividing) a score that starts at 1; subtracting and dividing never go
below 1. Besides an item's data, rules can see its metadata as
`meta`, e.g. `meta/triage/size` from [triage](#agents).

To figure out your rules, first set up your [sources](#sources), then run `mq up`,
then browse your monoqueue data in `~/.local/share/monoqueue/items.json` while
studying the rules above for inspiration. You can do it, I believe in you! <3

### Sources

Each section of `sources.conf` declares a source, of the kind its
`handler` names, which defaults to the section's name.

#### Firefox bookmarks

The bookmarks handler scans your local Firefox installation's bookmarks, and
creates an action item for each item within any folder whose name regex-matches
the configured one.

#### Firefox tabs

The tabs handler creates an action item for each open Firefox tab,
across all your devices. Tabs open on several devices become one item,
which also merges with matching items from other sources (e.g. a tab
showing a GitHub issue merges with that issue from the GitHub source).

Tabs come from the Firefox profiles of the computer running `mq up`:
its own open tabs, plus the tabs of your other devices as synced by
Firefox Sync. So on an always-on server, install Firefox and sign in to
Sync there. Firefox syncs when it starts, so it need not run all the
time: briefly running it headless before each update suffices, e.g.:

```
*/15 * * * * timeout 90 firefox --headless >/dev/null 2>&1; mq up tabs
```

Options:
- `exclude`: regular expressions, one per line, for URLs to ignore.
  Pinned tabs are always ignored.
- `max_device_age_days`: skip devices not seen for this many days (default 30).

Rules can use `tabs/device`, and `seconds_since_tab_access` for how long
ago you last looked at any of the item's tabs.

#### SciJava team

The scijava-team handler reads your community obligations from the
[SciJava team portal](https://status.scijava.org/team), and tags each
item with its roles there, for use in rules such as:

```ini
sj-review  = "reviewer_prs" in scijava/roles        -> +10: SciJava PR review
sj-release = "maintainer_releases" in scijava/roles -> +5: SciJava release
sj-stale   = "stale_status" in scijava/roles        -> +50: status page broken
```

Only roles listed in the `include` option (default:
`reviewer_prs, maintainer_releases`) create new items; other roles
(`support_issues`, `debugger_bugs`, `developer_features`) only tag items
found by other sources, so as not to flood the queue. Put the
`[scijava-team]` section after `[github]` so that those items exist first.

If the portal's data is older than `max_age_days` (default 2), an item
is added prompting you to fix the job that generates it.

#### CalDAV tasks

The caldav handler makes an action item of each open task (VTODO) on a
CalDAV server, such as Nextcloud, Fastmail, iCloud or Radicale:

```ini
[nextcloud]
handler = caldav
url = https://cloud.example.org/remote.php/dav
username = <your-username>
password = <an-app-password>
```

Options:
- `lists`: names of task lists to include, comma-separated (default: all).
- `link`: a URL template for opening tasks in a web app, with `{calendar}`,
  `{task}` and `{uid}` placeholders; by default, the task's CalDAV URL
  is used. E.g., for Nextcloud Tasks:
  `https://cloud.example.org/apps/tasks/calendars/{calendar}/tasks/{task}`
- `verify`: `false` to skip TLS certificate verification, or the path of a
  CA bundle or directory to trust, e.g. for a self-signed certificate.
  Note that certificates must name their host in a subjectAltName.

Completed and cancelled tasks are skipped. Rules can use `due` (and
`seconds_until_due`, negative when overdue), plus `task/priority`
(1 = highest, 9 = lowest, 0 = undefined), `task/list`, `task/categories`,
and `task/links` (URLs from the task's URL field and description):

```ini
due-soon      = seconds_until_due < 86400 -> +50: due within a day
high-priority = task/priority == 1        -> +20: high priority task
```

#### GitHub notifications

The notifications handler makes an action item of each unread GitHub
notification aimed at you personally: by default mentions, team
mentions, review requests and assignments, but not mere activity on
repositories you watch. Set `reasons` to a comma-separated list of
[notification reasons](https://docs.github.com/en/rest/activity/notifications#about-notification-reasons)
to change this. Like the GitHub handler, it uses a configured `token`,
or else that of the GitHub CLI. Rules can use `notification/reason`.

Notifications stay unread on GitHub until you read them or mark them done,
even once their issue or PR is closed. So the handler checks each one's
issue or PR, and drops review requests and assignments once moot: when
closed or merged, or no longer requesting or assigning you. Mentions are
kept, but rules can use `notification/state` (`open`, `closed`, or
`merged`), and for PRs, `notification/others_requested`, the number of
reviewers requested besides you:

```ini
closed      = notification/state in ("closed", "merged") -> -15: mentioned on a closed item
one-of-many = notification/others_requested >= 2         -> -20: one of several reviewers asked
```

#### GitHub

The GitHub handler connects to GitHub using the specified personal access token,
and pulls down all GitHub Issues (including Pull Requests) matching the given query.

If no token is configured and the [GitHub CLI](https://cli.github.com/)
is logged in, its token (from `gh auth token`) is used instead.

How to make a personal access token:
- https://github.com/settings/tokens &rarr; Generate new token &rarr; Generate new token (classic)
- Name the token whatever you want, use whatever expiration you want
- Scope: repo (Full control of private repositories)
- Click green "Generate token" button
- Copy the resulting token to your clipboard
- Paste it into `~/.config/monoqueue/sources.conf`
  as a `token = <your-token>` pair in a `[github]` section.

For performance across multiple invocations, GitHub content is cached beneath
`~/.cache/monoqueue/github/`, with subsequent queries being limited to updates
since the last query.

#### Discourse

The Discourse handler connects to a Discourse forum instance via its API using
the specified API key.

How to make a Discourse API key:
- https://forum.yourdiscourseinstance.com/admin/api/keys &rarr; New API Key
- Description: monoqueue (or whatever you want)
- User Level: Single User (your username)
- Scope: Read-only
- Click the blue "Save" button
- Copy the resulting key to your clipboard
- Paste it into `~/.config/monoqueue/sources.conf`
  as a `key = <your-api-key>` pair in the relevant Discourse section.
- Also add a `username = <your-username>` pair to that same section.

## Usage

Command          | Description
-----------------|------------
`mq up`          | Fetch items from configured sources (Firefox, GitHub, Discourse, etc.).
`mq up <source>` | Fetch items from only the given sources (e.g. `mq up tabs`).
`mq ui`          | Launch the interactive user interface.
`mq ls`          | List action items in plaintext.
`mq ls --html`   | List action items as an HTML report.
`mq info <url>`  | Show detailed info about an action item.
`mq triage <url>...` | Have an agent estimate items' size and next action.
`mq promote <url>` | Create a GitHub issue for an item, and link the item into it.
`mq link <url> <target>` | Link an item into another, e.g. a tab into an existing issue.
`mq tune <url> [--edit]` | Adjust the rules with an agent, from a misprioritized item.
`mq migrate-config` | Split an old `~/.config/monoqueue.conf` into `~/.config/monoqueue/`.

In `mq ui`, press `T` to triage the current item in the background, `A` to
work on it with an agent (`Shift+A` to edit the agent's prompt first), `R` to
adjust the rules when it seems misprioritized, and `I` to promote it to a GitHub issue.

### Agents

Triage asks an agent ([Claude Code](https://claude.com/claude-code), by
default) to summarize an item, estimate its size (XS to XL), and name its
next action and who must take it: you, an agent, or others, on whom you
are then waiting. The agent may look closer at the item (e.g. read an
issue's comments) but not change anything. Results are kept in the item's
metadata, for rules such as:

```ini
quick-win = meta/triage/size in ("XS", "S")  -> +5: quick win
waiting   = meta/triage/actor == "others"    -> /4: waiting on others
```

Working on an item with an agent opens an interactive agent session about
it, in a new tmux window (when in tmux), within the local clone of the
item's GitHub repository, if any. The agent looks into the item and
proposes a plan before changing anything.

Promoting an item has an agent draft a GitHub issue for it, including why
you care (if you say), which you can then edit before creating it, or not.
The item is then linked into the new issue: they remain one action item, at
the issue's URL, keeping the original's data (tabs, due date, and so on).

Tuning the rules starts from an item that seems misprioritized: you say
in your editor what is wrong with its priority, and why, and then an agent
(in a new tmux window, when in tmux) reads your rules, the item's data and
score, and proposes a change, explaining its effect on the queue, before
editing `rules.conf`. `mq ui` picks up rule changes as soon as they are
saved. Keeping `rules.conf` under version control makes changes easy to
review and undo.

Agents are configured in `settings.conf`:

```ini
[general]
about = I maintain open source software, and use monoqueue to prioritize
  my action items, which come from GitHub, forums, browser tabs, and more.

[agent]
model = sonnet

[triage]
model = haiku
```

In `[general]`:
- `about`: a few sentences about you and your work, giving agents context.
- `code_dir`: where clones of GitHub repositories live, as
  `<code_dir>/<owner>/<repo>` (default `~/code`).

In `[agent]`, defaults for all agents, which a section per action
(`[triage]`, `[work]`, `[promote]`, `[tune]`) may override:
- `command`: the agent command (default `claude`). It must accept Claude
  Code's options, and uses whatever account that command is logged in with.
- `model`: the model to use (default `sonnet`).
- `args`: extra arguments for interactive agents (work, tune) only, e.g.
  `--dangerously-skip-permissions`; triage and drafting always run with
  read-only tools.
- `timeout`: seconds to wait for triage and drafting (default 600).

And in `[promote]`:
- `repo`: where to create issues for items not clearly belonging to a
  particular repository, e.g. a public `tasks` repository of your own.

### Over ssh

When `mq ui` runs without a display, e.g. on a server you ssh into,
`(O)pen` copies the URL to the clipboard of the terminal you are using,
via OSC 52, rather than launching a console browser. The URL at the top
is also a terminal hyperlink (OSC 8) to the full URL, even when shown
abbreviated, so your terminal can open it with a click. Inside tmux,
both need `set -g set-clipboard on` and
`set -as terminal-features ',*:clipboard,*:hyperlinks'`.

### Status bars

After each update or deferral, monoqueue writes a one-line summary to
`~/.local/share/monoqueue/status`, for status bars such as byobu's:

```
<alerts> <due> <active> <written>
```

That is: the numbers of active alerts (e.g. failing sources), of active
items due within a day or overdue, and of all active items; and when
the summary was written, in seconds since the epoch.

### Sources and failures

Each source's items are saved separately, beneath
`~/.local/share/monoqueue/sources/`, and then merged into the queue in
configuration order: for an item reported by several sources, the title
from the first one wins. Merged items list their `sources`, for use in
rules such as `"tabs" in sources -> +5: open in a browser tab`.

If a source fails (e.g. an expired token), the queue keeps using its
items from its last success, and an alert item titled *Fix monoqueue
source: &lt;name&gt;* appears at the top of the queue, with the error
details in its description. It disappears once the source works again.

Since `mq up <source>` still merges the saved items of all sources,
sources can be refreshed on different schedules: e.g., tabs every 15
minutes, and everything else hourly.

### Logging

Set `DEBUG=1` for more detailed log messages, and `MONOQUEUE_LOG_FORMAT`
to change their [format](https://docs.python.org/3/library/logging.html#logrecord-attributes):
e.g., to timestamp them when logging from cron, add this line to your
crontab:

```
MONOQUEUE_LOG_FORMAT=%(asctime)s %(levelname)s %(message)s
```

## Limitations and pitfalls

> Well am I making haste or could it be haste is making me?  
> What's time but a thing to kill or keep or buy or lose or live in?  
> I gotta go faster, keep up the pace  
> Just to stay in the human race

&mdash;Bad Religion - [Supersonic](https://youtu.be/D0RKVCH6O0o)

* [Learn to say no sometimes](https://jamesclear.com/saying-no).
* [Taking breaks effectively is tricky](https://www.personneltoday.com/hr/breaks-from-work-mental-fatigue-study/)
* [Campbell's Law](https://en.wikipedia.org/wiki/Campbell%27s_law)
