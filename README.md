# Monoqueue

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

```shell
pip install monoqueue
```

Or from source:

```shell
pip install --user git+https://github.com/ctrueden/monoqueue.git#egg=monoqueue
```

And put `~/.local/bin` on your path.

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

#### GitHub

The GitHub handler connects to GitHub using the specified personal access token,
and pulls down all GitHub Issues (including Pull Requests) matching the given query.

How to make a personal access token:
- https://github.com/settings/tokens &rarr; Generate new token &rarr; Generate new token (classic)
- Name the token whatever you want, use whatever expiration you want
- Scope: repo (Full control of private repositories)
- Click green "Generate token" button
- Copy the resulting token to your clipboard
- Paste it into `~/.config/monoqueue.conf`
  as a `token = <your-token>` pair in a `[github]` section.

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
`mq ui`          | Launch the interactive user interface.
`mq ls`          | List action items in plaintext.
`mq ls --html`   | List action items as an HTML report.
`mq info <url>`  | Show detailed info about an action item.

## Limitations and pitfalls

> Well am I making haste or could it be haste is making me?  
> What's time but a thing to kill or keep or buy or lose or live in?  
> I gotta go faster, keep up the pace  
> Just to stay in the human race

&mdash;Bad Religion - [Supersonic](https://youtu.be/D0RKVCH6O0o)

* [Learn to say no sometimes](https://jamesclear.com/saying-no).
* [Taking breaks effectively is tricky](https://www.personneltoday.com/hr/breaks-from-work-mental-fatigue-study/)
* [Campbell's Law](https://en.wikipedia.org/wiki/Campbell%27s_law)
