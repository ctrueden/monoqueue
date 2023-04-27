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
git clone https://github.com/ctrueden/monoqueue
pip install --user -e monoqueue
```

And put `~/.local/bin` on your path.

## Configuration

```shell
vi ~/.config/monoqueue.conf
```

Then add content of the form:

```ini
[firefox]
folder = ACTION

[github]
token = <your-github-api-token>
query = org:my-favorite-org+org:my-other-favorite-org+repo:a-repo-I-manage

[forum.example.com]
handler = discourse
username = <your-discourse-username-on-forum.example.com>
key = <discourse-api-key-for-forum.example.com>
query = #a-category-to-search tags:foo,bar,stuff status:open status:unsolved
...
```

Then protect your secrets:

```shell
chmod 600 ~/.config/monoqueue.conf
```

Each configuration section declares a source.

### Firefox

The Firefox handler scans your local Firefox installation's bookmarks, and
creates an action item for each item within any folder whose name regex-matches
the configured one.

### GitHub

The GitHub handler connects to GitHub using the specified personal access token,
and pulls down all GitHub Issues (including Pull Requests) matching the given query.

How to make a personal access token:
- https://github.com/settings/tokens &rarr; Generate new token &rarr; Generate new token (classic)
- Name the token whatever you want, use whatever expiration you want
- Scope: repo (Full control of private repositories)
- Click green "Generate token" button
- Copy the resulting token to your clipboard
- Paste it into `~/.config/monoqueue.conf`
  as a `github = <your-token>` pair in a `[tokens]` section.

### Discourse

The Discourse handler connects to a Discourse forum instance via its API using
the specified API key.

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
