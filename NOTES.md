# Unsorted notes

This project will resolve the following issue:
https://github.com/ctrueden/tasks/issues/12

One single place with support requests sorted by date
Requirements:
- low maintenance burden
- add browser tab to queue/bookmarks with keyboard shortcut
- include list of all open PRs in my orgs(?), and esp all PRs I am a requested reviewer of
- Emails -- list of all starred
- speed is paramount: e.g. can I make the email links open in my existing email tab rather than opening new tabs?
- what about habitica todos and dailies? Separate? Then I need to BLOCK TIME for support queue!
- all queue entries must have a URL, and must be datestamped!
  - firefox bookmarks have an added/updated date
  - gmail starred messages have a datestamp
  - forum.image.sc / discourse bookmarks point to topics with datestamps
  - source plugins must provide this info in their feed
- heuristic for sorting: want to handle the past few (10?) days first, but then sort by OLDEST?
- Operations: ls/list, update
- output modes? Plaintext, markdown, html, xml
- Interactivity? Mainly just REMOVAL of items, and REQUEUING. But details are fuzzy. Must be fast!
  - removal of browser bookmarks from browser is actually fine, IF ctrl+D unbookmarks an already-bookmarked tab
  - is there a kb shortcut for discourse book/unbook?
  - but what if sync is 2 way? Then can edit plaintext queue and sync up to unbook stuff also -- need to remember last sync date

I have the following categories of support:

* Replying to email
* Replying to topics on Image.sc Forum
* Replying to GitHub issues
* Reviewing and/or merging GitHub PRs
* Taking some other action related to a URL

I also have a [Community support project board](https://github.com/users/ctrueden/projects/1/views/1), but I hate it because it's too much manual effort. (Maybe I could sync my support queue status to this board automatically, for public viewing?)

There are also Habitica To Do's, but those can probably remain separate.

I want to sort the support feeds by an impact score, and then work on items in impact order.

But email specifically does not need to be part of this queue. Rather:
- When an email needs action relating to a URL (e.g. Image.sc or GitHub), use that URL instead.
- For whatever's left, and actually needing an *email reply*, star it.
- Make an effort to tackle all starred emails ASAP, so starred mailbox remains minimal.
- To defer an email thread till a later date, use Snooze.

For those remaining feeds, considerations include:
- Who's court is the ball in? If I'm waiting for external action, it goes from ACTION to DEFERRED status.
  - But maybe only "deferred until" some particular amount of time has passed. How to specify this?
- The date of the most recent interaction matters:
  - For very recent things, continue striking while the iron is hot.
  - For very old things, reply sooner, just to close out the topic so it's not hanging forever.
  - For things in between, maybe the urgency decreases... but what does "in between" mean?

Some of the feeds provide tools to managing them:
- GitHub provides *assignee* for issues, and *requested reviewer* for PRs.
- Image.sc Forum provides *bookmarks*, including optional reminder timestamps.
- Firefox bookmarks (for arbitrary URLs) provide created and last modified timestamps, although these are *not* synced by Firefox Sync.

Can my queue be simply bookmarked URLs in Firefox?
- A browser extension could be used to [manage bookmarks in JS](https://developer.mozilla.org/en-US/docs/Mozilla/Add-ons/WebExtensions/Work_with_the_Bookmarks_API).
  - Maybe sync them to a file on disk, and watch that file for external changes?
  - Or Firefox's [native messaging API](https://developer.mozilla.org/en-US/docs/Mozilla/Add-ons/WebExtensions/Native_messaging) could be used to communicate live with my monoqueue program?
    - It uses JSON over stdin/stdout... can I plug my extension together with Appose?
    - [This project](https://github.com/NiklasGollenstede/native-ext) might (or might not) also be useful.
  - Meanwhile, the monoqueue native app would:
    - load data from api.github.com
    - load data from a Discourse API feed
    - use this information to rename bookmarks to match computed impact factor
  - What about deferral? Need a syntax... separate from impact factor, just: "do not show me this again till X date"
    - as simple as prefixing the date before the impact factor? E.g. `[2023-04-11] {57} Title of the Page`
- can I delete them externally? if not: ctrl+D to remove after completed
- can I rename them programmatically, so that sorting them yields the correct order?
- maybe a browser extension?
  - and... anything else? Deferral? How to snooze?

OR: do not rename bookmarks, just bookmark them, then harvest them into monoqueue without needing an FF extension. I wrote the code already to do this by digging in the sqlite3 DB, although it's kind of wonky.
* For each URL imported into monoqueue (from anywhere, not necessarily Firefox), compute its impact factor and add it to my local plaintext queue!

----------------------

Plaintext queue, a la Org mode -- but not actually Org mode.

For each source, we have:
- a list of URLs, each of which represents an action item
- a bag of metadata, available for use by the scorer

Supported sources include:
- Firefox bookmarks
- GitHub Issues
- Discourse forum topics
- Zulip chat threads

For each source, we acquire these two things.

Then we *score* each action item using the scorer.

1. Acquire JSON data within each source's sphere of interest.
What should the data structure be? dict on URL keys? or list?

Why the complication? Want to minimize API queries to reduce glacial load times and 403 Forbidden errors.

So: we get the sphere, then sort through the sphere for ACTION ITEMS matching filter rules.
But we don't discard non-matching sphere items, because other sources might benefit from those.

for Discourse:
https://github.com/samamorgan/discourse
https://pypi.org/project/discourse/
https://docs.discourse.org/

1. Define your SPHERE
   - for each SOURCE: fetch only those things 
   - URLs are KEYS
   - metadata from multiple sources about the same URL are UNIONED
2. Fetch all items from that sphere
3. Score all fetched items

Two modes:
- rapid response = multiply items by how recent they are
- backlog tackle = multiply items by how old they are
- either way: maybe use inverse distance squared?

Needed info:
* from GitHub:
  * which orgs am I responsible for? Hardcoded list?
  * which repos do I maintain? Can check the pom.xml or pyproject.toml of that repo on main branch.
  * Are there GitHub query terms that would be effective here?
* from Discourse:
  * which topics are unanswered, and tagged with tags I'm supporting, in categories I'm supporting?
  * which topics have mentioned me?
* from Zulip:
  * is the topic resolved?
  * was I @ mentioned?
  * who responded last?
  * do I even care about this one?

Performance metrics to track:
- Number of starred emails at beginning and end of day
- Number of open GitHub issues assigned to me
- Number of open GitHub issues in repos I maintain
- Number of open GitHub PRs assigned to me
- Number of open GitHub PRs with me as a requested reviewer
- Number of open GitHub PRs in repos I maintain
- Number of Image.sc forum topics in my sphere 

## Discarded ideas

### Firefox browser extension

To make bookmark syncing work better, a browser extension could be used to [manage bookmarks in JS](https://developer.mozilla.org/en-US/docs/Mozilla/Add-ons/WebExtensions/Work_with_the_Bookmarks_API).
- Maybe sync them to a file on disk, and watch that file for external changes?
- Or Firefox's [native messaging API](https://developer.mozilla.org/en-US/docs/Mozilla/Add-ons/WebExtensions/Native_messaging) could be used to communicate live with my monoqueue program?
  - It uses JSON over stdin/stdout... can I plug my extension together with Appose?
  - [This project](https://github.com/NiklasGollenstede/native-ext) might (or might not) also be useful.

