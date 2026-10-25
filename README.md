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

```shell
vi ~/.config/monoqueue.conf
```

Then add content of the form:

```ini
[rules]
rule01 = bookmark                                   -> +20: action bookmark

rule10 = issue/pull_request                         -> +20: pull request
rule11 = "ctrueden" in issue/assignees/login        -> +5: assigned to me
rule12 = ["ctrueden"] == issue/assignees/login      -> +5: assigned to only me
rule13 = "/monoqueue/" in issue/url                 -> +5: favorite project (monoqueue)
rule14 = issue/milestone/title == "next-release"    -> +3: next-release milestone
rule15 = "@ctrueden" in issue/body                  -> +2: mentions me
rule16 = issue/author_association == "CONTRIBUTOR"  -> +5: issue author is non-member
rule17 = issue/state == "open"                      -> +1: open issue
rule18 = issue/reactions/total_count                -> +X: number of reactions
rule19 = issue/comments                             -> +X: number of comments
rule20 = issue/draft                                -> -2: draft PR

rule50 = topic/has_accepted_answer is False         -> +5: has no accepted answer
rule51 = "monoqueue" in topic/tags                  -> +5: monoqueue tag

# 10 min = +12960; 1 hour = +2160; 8 hours = +270; 1 day = +90; 1 week = +10; 2 weeks = +5; 1 month = +2
rule77 = 7776000 / seconds_since_update             -> +X: time since last update (rapid response)
#rule77 = seconds_since_update / 86400               -> +X: days since last update (backlog tackle)

rule99 = issue/milestone/title == "unscheduled"     -> /100: unscheduled milestone

[firefox]
folder = ACTION

[github]
token = <your-github-api-token>
query = is:open+org:my-favorite-org+org:my-other-favorite-org+repo:a-repo-I-manage

[tabs]
exclude =
  ^https://mail\.google\.com/
  ^https://calendar\.google\.com/

[scijava]
dev_id = <your-scijava-developer-id>

[forum.example.com]
handler = discourse
username = <your-discourse-username-on-forum.example.com>
key = <discourse-api-key-for-forum.example.com>
query = #a-category-to-search tags:foo,bar,stuff status:open status:unsolved
```

Then protect your secrets:

```shell
chmod 600 ~/.config/monoqueue.conf
```

### Rules

Rules are written in Python syntax, parsed by Python's `ast` module, and evaluated
using a custom evaluator to avoid calling the insecure `eval` function. The monoqueue
evaluator supports standard Python unary and binary operators, as well as a special
overload of the divide (`/`) operator for digging into nested data structures easily.

To figure out your rules, first set up your [sources](#sources), then run `mq up`,
then browse your monoqueue data in `~/.local/share/monoqueue/items.json` while
studying the rules above for inspiration. You can do it, I believe in you! <3

### Sources

Apart from the `[rules]`, each configuration section declares a source.

#### Firefox

The Firefox handler scans your local Firefox installation's bookmarks, and
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

The scijava handler reads your community obligations from the
[SciJava team portal](https://status.scijava.org/team), and tags each
item with its roles there, for use in rules such as:

```ini
rule30 = "reviewer_prs" in scijava/roles      -> +10: SciJava PR review
rule31 = "maintainer_releases" in scijava/roles -> +5: SciJava release
rule32 = "stale_status" in scijava/roles      -> +50: status page broken
```

Only roles listed in the `include` option (default:
`reviewer_prs, maintainer_releases`) create new items; other roles
(`support_issues`, `debugger_bugs`, `developer_features`) only tag items
found by other sources, so as not to flood the queue. Put the
`[scijava]` section after `[github]` so that those items exist first.

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
rule40 = seconds_until_due < 86400 -> +50: due within a day
rule41 = task/priority == 1        -> +20: high priority task
```

#### GitHub notifications

The notifications handler makes an action item of each unread GitHub
notification aimed at you personally: by default mentions, team
mentions, review requests and assignments, but not mere activity on
repositories you watch. Set `reasons` to a comma-separated list of
[notification reasons](https://docs.github.com/en/rest/activity/notifications#about-notification-reasons)
to change this. Like the GitHub handler, it uses a configured `token`,
or else that of the GitHub CLI. Rules can use `notification/reason`.

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
- Paste it into `~/.config/monoqueue.conf`
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
- Paste it into `~/.config/monoqueue.conf`
  as an `key = <your-api-key>` pair in the relevant Discourse section.
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
