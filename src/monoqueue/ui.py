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

import curses, datetime, re, sys, webbrowser

from . import Monoqueue, now, s2dt

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


class UI:
    def __init__(self, stdscr):
        self.mq = Monoqueue()
        self.mq.load()
        self.stdscr = stdscr
        self.jump(0)

    def refresh(self):
        self.stdscr.refresh()

    def draw_screen(self):
        self.stdscr.clear()

        info = self.mq.info(self.url)
        created = info["created"]
        updated = info["updated"]
        impact = self.mq.impact(self.url)

        self.write(self.url, 0, c=C_URL)
        self.write(info["title"], 1, c=C_TITLE)

        lc_indent = 2
        rc_indent = 40
        # Left column
        self.write(f"Created: {created}", 3, lc_indent, c=C_DATES)
        self.write(f"Updated: {updated}", 4, lc_indent, c=C_DATES)
        self.write(f"Age: {now() - s2dt(updated)}", 5, lc_indent, c=C_DATES)
        l_row = 6
        # Right column
        self.write(f"Impact: {impact}", 3, rc_indent, c=C_SCORE)
        r_row = 4
        for rule in info["score"]["rules"]:
            self.write(f"* {rule}", r_row, rc_indent, c=C_SCORE)
            r_row += 1

        row = max(l_row, r_row)
        self.draw_divider(row + 1)
        self.write(f"Action item {self.index + 1} of {self.count}", row + 2, 0)
        self.write("", row + 3, 0)
        self.draw_option_line("(O)pen | (N)ext | (P)revious | Defer (1)(2)(3)... | (Q)uit")
        self.write("> ", row + 5, 0)

    def draw_option_line(self, s):
        option = False
        for token in re.split("(\([A-Z0-9]\))", s):
            self.write(token, c=C_OPTION if option else 0)
            option = not option

    def draw_divider(self, y):
        self.write("-" * curses.COLS, y, 0)

    def write(self, msg, y=None, x=None, c=0):
        s = str(msg)
        if y is not None and x is None:
            # center the string, truncating with ellipses if needed
            if len(s) > curses.COLS:
                s = s[:curses.COLS-3] + "..."
            x = max(0, (curses.COLS - len(s)) // 2)
        if x is None and y is None:
            self.stdscr.addstr(s, curses.color_pair(c))
        else:
            self.stdscr.addstr(y, x, s, curses.color_pair(c))

    def quit(self, exit_code=0):
        sys.exit(exit_code)

    def readkey(self):
        key = self.stdscr.getkey()
        self.write(key)
        self.refresh()
        return key

    def do_operation(self, key):
        if key in "oO":
            webbrowser.open(self.url)
        if key in "nN":
            self.jump(self.index + 1)
        if key in "pP":
            self.jump(self.index - 1)
        if key in "qQ":
            self.quit()
        if key in "123456789":
            days = ord(key) - ord('0')
            self.defer(days)
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

    def defer(self, days):
        self.mq.defer(self.url, now() + datetime.timedelta(days=days))


def main(*args):
    curses.wrapper(lambda stdscr: UI(stdscr).loop())


if __name__ == "__main__":
    main(*sys.argv[1:])
