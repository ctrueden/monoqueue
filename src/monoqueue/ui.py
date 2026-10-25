#!/usr/bin/env python
#
# This is free and unencumbered software released into the public domain.
# See the UNLICENSE file for details.
#
# ------------------------------------------------------------------------
# ui.py
# ------------------------------------------------------------------------

"""
A curses-based user interface to monoqueue.
"""

import base64
import contextlib
import curses
import os
import re
import subprocess
import sys
import webbrowser
from pathlib import Path

from . import Monoqueue, agent, promote, time

# A nice curses tutorial can be found at:
# https://docs.python.org/3/howto/curses.html#curses-howto
#
# If UI widgets are needed: https://pypi.org/project/urwid/


C_OPTION = 1
C_HILITE = 2
C_URL = 3
C_TITLE = 4
C_DATES = 5
C_SCORE = 6

K_UP = (75, 69, 89, 95, 85, 80)
K_DN = (75, 69, 89, 95, 68, 79, 87, 78)
K_LT = (75, 69, 89, 95, 76, 69, 70, 84)
K_RT = (75, 69, 89, 95, 82, 73, 71, 72, 84)
K_PGUP = (75, 69, 89, 95, 80, 80, 65, 71, 69)
K_PGDN = (75, 69, 89, 95, 78, 80, 65, 71, 69)
K_HOME = (75, 69, 89, 95, 72, 79, 77, 69)
K_END = (75, 69, 89, 95, 69, 78, 68)
K_CTRL_B = (2,)
K_CTRL_D = (4,)
K_CTRL_F = (6,)
K_CTRL_U = (21,)

class UI:
    def __init__(self, stdscr):
        self.mq = Monoqueue()
        self.mq.load()
        self.metadata_mtime = _mtime(Monoqueue._DEFAULT_METADATA_PATH)
        self.stdscr = stdscr
        self.url = None
        self.index = None
        self.count = None
        self.scroll_offset = None
        self.message = None
        self.link = None
        self.jump(0)

    def refresh(self):
        self.stdscr.refresh()
        self.draw_link()

    def draw_link(self):
        """
        Make the URL a hyperlink (OSC 8) to the full URL, so that clicking it
        works even when it is shown truncated.

        curses cannot emit hyperlinks, so this rewrites the URL's text
        directly to the terminal, behind curses's back. The rewritten text is
        identical, so curses's idea of the screen remains accurate.
        """
        if not self.link: return
        y, x, text = self.link
        sys.stdout.write(
            "\0337"  # Save cursor position and attributes.
            f"\033[{y + 1};{x + 1}H\033[36;40m"
            f"\033]8;;{self.url}\033\\{text}\033]8;;\033\\"
            "\0338"  # Restore them.
        )
        sys.stdout.flush()

    def draw_screen(self):
        self.stdscr.clear()

        item = self.mq.item(self.url)
        created = item.get("created")
        updated = item.get("updated")
        impact = self.mq.impact(self.url)
        issue = item.get("issue")
        body = UI.split_lines(issue.get("body") if issue else item.get("description"), 0)

        row = -1
        self.write(self.url, (row := row + 1), c=C_URL)
        text = UI.trunc_line(self.url, curses.COLS)
        self.link = (row, (curses.COLS - len(text)) // 2, text)
        self.write(item["title"], (row := row + 1), c=C_TITLE)

        self.draw_divider(row := row + 1)
        self.write(f"Action item {self.index + 1} of {self.count}", (row := row + 1), 0)
        self.write("", (row := row + 1), 0)
        self.draw_option_line("(O)pen (N)ext (P)rev | Defer (1)(2)(3)... | (T)riage (A)gent (I)ssue | (Q)uit")
        prompt_row = (row := row + 1)
        self.draw_divider(row := row + 1)

        # Left column
        l_row = row
        l_col = 2
        self.write(f"Created: {created or '?'}", (l_row := l_row + 1), l_col, c=C_DATES)
        self.write(f"Updated: {updated or '?'}", (l_row := l_row + 1), l_col, c=C_DATES)
        if updated:
            self.write(f"Age: {time.age(updated)}", (l_row := l_row + 1), l_col, c=C_DATES)

        # Right column
        r_row = row
        r_col = 40
        self.write(f"Impact: {impact.value:.1f}", (r_row := r_row + 1), r_col, c=C_SCORE)
        for rule in impact.rules:
            self.write(f"* {rule}", (r_row := r_row + 1), r_col, c=C_SCORE)

        # Triage, links, and notes, if any
        row = max(l_row, r_row)
        metadata = self.mq.metadata(self.url)
        notes = []
        triaged = metadata.get("triage")
        if triaged:
            notes.append(f"Size {triaged['size']} ({agent.SIZES.get(triaged['size'], '?')}); "
                         f"next action ({triaged['actor']}): {triaged['next_action']}")
        if metadata.get("note"): notes.append(f"Note: {metadata['note']}")
        if metadata.get("links"): notes.append(f"Links: {', '.join(metadata['links'])}")
        if notes:
            self.draw_divider(row := row + 1)
            for line in UI.split_lines("\n".join(notes), 0):
                self.write(line, (row := row + 1), 0, c=C_HILITE)

        # Body, if available
        self.draw_divider(row := row + 1)

        if body:
            max_offset = len(body) - curses.LINES + row + 1
            self.scroll_offset = max(0, min(self.scroll_offset, max_offset))
            for i in range(self.scroll_offset, len(body)):
                self.write(body[i], (row := row + 1), 0)
                if row >= curses.LINES: break

        if self.message:
            self.write(self.message, prompt_row, 4, c=C_HILITE)
            self.message = None

        # Cursor prompt
        self.write("> ", prompt_row, 0)

    def draw_option_line(self, s):
        option = False
        for token in re.split("(\\([A-Z0-9]\\))", s):
            self.write(token, c=C_OPTION if option else 0)
            option = not option

    def draw_divider(self, y):
        self.write("-" * curses.COLS, y, 0)

    @staticmethod
    def trunc_line(line, max_len):
        if len(line) <= max_len: return line
        end = max_len - 3
        return "" if end < 0 else line[:end] + "..."

    @staticmethod
    def split_lines(s, x):
        """
        Split up a multi-line message block, intelligently wrapping at words.
        """
        lines = []
        if s is None: return lines

        max_len = curses.COLS - x
        code = False
        for line in re.split("\r\n|\n", s.replace("\t", "    ")):
            if line.startswith("```"): code = not code
            tack = True
            while len(line) > max_len:
                if code:
                    # No line splitting inside a code fence.
                    end = len(line)
                    tack = False
                else:
                    # Split up long lines on words.
                    end = line[:max_len].rfind(" ")
                    if end < 0: end = line.find(" ", max_len)
                    if end < 0: end = len(line)

                lines.append(line[:end])
                line = line[end + 1:]

            if tack: lines.append(line)

        return lines

    def write(self, msg, y=None, x=None, c=0):
        s = str(msg)
        if y is None:
            # Draw the string at the current cursor position.
            self.stdscr.addstr(s, curses.color_pair(c))
            return

        if x is None:
            # Center the string, truncating with ellipses if needed.
            s = UI.trunc_line(s, curses.COLS)
            x = (curses.COLS - len(s)) // 2

        if x >= curses.COLS or y >= curses.LINES:
            # String is out of bounds; draw nothing.
            return

        if x < 0 or y < 0:
            raise ValueError(f"Invalid coordinates: {y=}, {x=}")

        s = UI.trunc_line(s, curses.COLS - x)
        try:
            self.stdscr.addstr(y, x, s, curses.color_pair(c))
        except:
            # Every so often, curses crashes while resizing the terminal.
            # Ignoring these errors seems to behave just fine, so we do.
            pass

    def quit(self, exit_code=0):
        sys.exit(exit_code)

    def readkey(self):
        try:
            key = self.stdscr.getkey()
        except curses.error:
            return None  # No key pressed before the timeout.
        self.write(key)
        self.refresh()
        return key

    def do_operation(self, key: str):
        code = tuple(ord(c) for c in key)
        if key in "oO": self.open()
        elif key in "nN": self.jump(self.index + 1)
        elif key in "pP": self.jump(self.index - 1)
        elif key in "qQ": self.quit()
        elif key in "tT": self.triage()
        elif key in "aA": self.work()
        elif key in "iI": self.promote()
        elif key in "123456789": self.defer(ord(key) - ord('0'))
        elif key in "jJ" or code == K_DN: self.scroll(1)
        elif key in "kK" or code == K_UP: self.scroll(-1)
        elif code in (K_PGDN, K_CTRL_D, K_CTRL_F): self.scroll(curses.LINES // 2)
        elif code in (K_PGUP, K_CTRL_U, K_CTRL_B): self.scroll(-curses.LINES // 2)
        elif code == K_HOME: self.scroll(-2**30)
        elif key == "G" or code == K_END: self.scroll(2**30)
        return True

    def open(self):
        """
        Open the URL in a browser, if there is a display to show one; or else,
        e.g. when connected via ssh, copy the URL to the clipboard of the
        terminal you are using (OSC 52), rather than open a console browser.
        """
        if _has_display():
            webbrowser.open(self.url)
            return
        data = base64.b64encode(self.url.encode()).decode()
        sys.stdout.write(f"\033]52;c;{data}\a")
        sys.stdout.flush()
        self.message = "Copied URL to clipboard"

    def triage(self):
        """
        Triage the item in the background; the result appears once done.
        """
        log_path = Path("~/.cache/monoqueue/agent.log").expanduser()
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "a") as log_file:
            subprocess.Popen(
                [sys.executable, "-m", "monoqueue", "triage", self.url],
                stdin=subprocess.DEVNULL, stdout=log_file, stderr=log_file,
                start_new_session=True,
            )
        self.message = "Triaging in the background; the result will appear here"

    def work(self):
        """
        Work on the item with an agent: in a new tmux window, if in tmux,
        so that the queue remains at hand; or else in this terminal.
        """
        args, cwd = agent.work_command(self.mq, self.url, self.mq.section("agent"))
        if os.environ.get("TMUX"):
            window = ["tmux", "new-window", "-n", "agent"]
            if cwd: window += ["-c", str(cwd)]
            subprocess.run(window + args, check=False)
            self.message = "Opened an agent in a new tmux window"
            return
        with self.suspended():
            subprocess.run(args, cwd=cwd, check=False)

    def promote(self):
        """
        Promote the item to a GitHub issue, on the terminal, since that
        involves reading and perhaps editing the drafted issue.
        """
        try:
            promote.check_promotable(self.mq, self.url)
        except ValueError as e:
            self.message = f"Cannot promote: {e}"
            return
        with self.suspended():
            print(f"{self.url}\n{self.mq.item(self.url).get('title')}\n")
            try:
                why = input("Why do you care about this? (optional) ").strip()
                issue_url = promote.interact(self.mq, self.url, why)
            except (Exception, KeyboardInterrupt) as e:
                issue_url = None
                print(f"\nNot promoted: {e}")
            self.mq.save(items_path=None)
            input("\nPress Enter to return to the queue...")
        if issue_url:
            self.jump(self.mq.urls().index(issue_url) if issue_url in self.mq.urls() else self.index)

    @contextlib.contextmanager
    def suspended(self):
        """
        Leave curses mode temporarily, e.g. to run a terminal program.
        """
        curses.def_prog_mode()
        curses.endwin()
        try:
            yield
        finally:
            curses.reset_prog_mode()
            self.stdscr.clear()
            self.refresh()

    def check_metadata(self):
        """
        Pick up metadata changed by other processes, e.g. a triage.

        :return:
            True if the metadata changed.
        """
        mtime = _mtime(Monoqueue._DEFAULT_METADATA_PATH)
        if mtime == self.metadata_mtime: return False
        self.metadata_mtime = mtime
        self.mq.reload_metadata()
        return True

    def loop(self):
        curses.init_pair(C_OPTION, curses.COLOR_RED, curses.COLOR_BLACK)
        curses.init_pair(C_HILITE, curses.COLOR_YELLOW, curses.COLOR_BLACK)
        curses.init_pair(C_URL, curses.COLOR_CYAN, curses.COLOR_BLACK)
        curses.init_pair(C_TITLE, curses.COLOR_GREEN, curses.COLOR_BLACK)
        curses.init_pair(C_DATES, curses.COLOR_BLUE, curses.COLOR_BLACK)
        curses.init_pair(C_SCORE, curses.COLOR_MAGENTA, curses.COLOR_BLACK)

        # NB: Wait for keys only briefly, to notice metadata changes.
        self.stdscr.timeout(2000)
        redraw = True
        while True:
            if self.check_metadata() or redraw:
                self.draw_screen()
                self.refresh()
            key = self.readkey()
            redraw = key is not None
            if redraw: self.do_operation(key)

    def jump(self, index):
        urls = self.mq.urls()
        self.count = len(urls)
        self.index = max(0, min(index, self.count - 1))
        self.url = urls[self.index]
        self.scroll_offset = 0

    def defer(self, days):
        self.mq.defer(self.url, time.days_later(days))

        # Persist the updated metadata to disk.
        self.mq.save(items_path=None)
        self.mq.save_status()

        # Refresh the display.
        self.jump(self.index)

    def scroll(self, amount):
        self.scroll_offset += amount
        if self.scroll_offset < 0: self.scroll_offset = 0

def _mtime(path):
    try:
        return path.stat().st_mtime
    except OSError:
        return None


def _has_display():
    if sys.platform in ("darwin", "win32"): return True
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def main(*args):
    curses.wrapper(lambda stdscr: UI(stdscr).loop())


if __name__ == "__main__":
    main(*sys.argv[1:])
