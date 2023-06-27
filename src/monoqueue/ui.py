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

import curses
import re
import sys
import webbrowser

from . import Monoqueue, time

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

class UI:
    def __init__(self, stdscr):
        self.mq = Monoqueue()
        self.mq.load()
        self.stdscr = stdscr
        self.url = None
        self.index = None
        self.count = None
        self.scroll_offset = None
        self.jump(0)

    def refresh(self):
        self.stdscr.refresh()

    def draw_screen(self):
        self.stdscr.clear()

        item = self.mq.item(self.url)
        created = item["created"]
        updated = item["updated"]
        impact = self.mq.impact(self.url)
        issue = item.get("issue")
        body = UI.split_lines(issue.get("body"), 0) if issue else None

        row = -1
        self.write(self.url, (row := row + 1), c=C_URL)
        self.write(item["title"], (row := row + 1), c=C_TITLE)

        self.draw_divider(row := row + 1)
        self.write(f"Action item {self.index + 1} of {self.count}", (row := row + 1), 0)
        self.write("", (row := row + 1), 0)
        self.draw_option_line("(O)pen | (N)ext | (P)revious | Defer (1)(2)(3)... | (Q)uit")
        prompt_row = (row := row + 1)
        self.draw_divider(row := row + 1)

        # Left column
        l_row = row
        l_col = 2
        self.write(f"Created: {created}", (l_row := l_row + 1), l_col, c=C_DATES)
        self.write(f"Updated: {updated}", (l_row := l_row + 1), l_col, c=C_DATES)
        self.write(f"Age: {time.age(updated)}", (l_row := l_row + 1), l_col, c=C_DATES)

        # Right column
        r_row = row
        r_col = 40
        self.write(f"Impact: {impact.value}", (r_row := r_row + 1), r_col, c=C_SCORE)
        for rule in impact.rules:
            self.write(f"* {rule}", (r_row := r_row + 1), r_col, c=C_SCORE)

        # Body, if available
        row = max(l_row, r_row)
        self.draw_divider(row := row + 1)

        if body:
            max_offset = len(body) - curses.LINES + row + 1
            self.scroll_offset = max(0, min(self.scroll_offset, max_offset))
            for i in range(self.scroll_offset, len(body)):
                self.write(body[i], (row := row + 1), 0)
                if row >= curses.LINES: break

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
        key = self.stdscr.getkey()
        self.write(key)
        self.refresh()
        return key

    def do_operation(self, key: str):
        code = tuple(ord(c) for c in key)
        if key in "oO": webbrowser.open(self.url)
        elif key in "nN": self.jump(self.index + 1)
        elif key in "pP": self.jump(self.index - 1)
        elif key in "qQ": self.quit()
        elif key in "123456789": self.defer(ord(key) - ord('0'))
        elif key in "jJ" or code == K_DN: self.scroll(1)
        elif key in "kK" or code == K_UP: self.scroll(-1)
        elif code == K_PGDN: self.scroll(curses.LINES // 2)
        elif code == K_PGUP: self.scroll(-curses.LINES // 2)
        return True

    def loop(self):
        curses.init_pair(C_OPTION, curses.COLOR_RED, curses.COLOR_BLACK)
        curses.init_pair(C_HILITE, curses.COLOR_YELLOW, curses.COLOR_BLACK)
        curses.init_pair(C_URL, curses.COLOR_CYAN, curses.COLOR_BLACK)
        curses.init_pair(C_TITLE, curses.COLOR_GREEN, curses.COLOR_BLACK)
        curses.init_pair(C_DATES, curses.COLOR_BLUE, curses.COLOR_BLACK)
        curses.init_pair(C_SCORE, curses.COLOR_MAGENTA, curses.COLOR_BLACK)

        while True:
            self.draw_screen()
            key = self.readkey()
            self.do_operation(key)

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

        # Refresh the display.
        self.jump(self.index)

    def scroll(self, amount):
        self.scroll_offset += amount
        if self.scroll_offset < 0: self.scroll_offset = 0

def main(*args):
    curses.wrapper(lambda stdscr: UI(stdscr).loop())


if __name__ == "__main__":
    main(*sys.argv[1:])
