#!/usr/bin/env python
#
# This is free and unencumbered software released into the public domain.
# See the UNLICENSE file for details.
#
# ------------------------------------------------------------------------
# github.py
# ------------------------------------------------------------------------

"""
Routines to download and organize information from GitHub.
"""

import json, sys, time

import requests

from .log import log


def update(mq, config):
    token = config["token"]
    query = config["query"]

    ghi = GitHubIssues(token=token)
    ghi._progress = mq.progress
    ghi.download(query)

    for issue in ghi.issues:
        url = issue["html_url"]
        if not url in mq.items:
            mq.items[url] = {}

        mq.items[url].update({
            "title": issue["title"],
            "created": issue["created_at"],
            "updated": issue["updated_at"],
            "issue": issue
        })


class GitHubIssues:

    @staticmethod
    def _search_url(query):
        return f"https://api.github.com/search/issues?q={query}&sort=created&order=asc&per_page=100"

    def __init__(self, items=None, token=None):
        self._token = token
        self.issues = [] if items is None else items
        self._delay_per_request = 7
        self._max_requests = 100
        self._progress = None

    def load(self, filepath):
        """
        Load issues from the given JSON file.
        """
        with open(filepath) as f:
            result = json.loads(f.read())
            self.issues.extend(result)

    def save(self, filepath):
        """
        Save issues to the given JSON file.
        """
        with open(filepath, 'w') as f:
            return json.dump(self.issues, f, sort_keys=True, indent=4)

    def download(self, query):
        """
        Download issues from GitHub according to the given query.
        """
        url = GitHubIssues._search_url(query)
        for _ in range(self._max_requests):
            url = self._download_page(url, query)
            if self._progress: self._progress(url)
            if not url: break
            time.sleep(self._delay_per_request)

    def _download_page(self, url, query):
        headers = {'User-Agent': 'monoqueue'}
        if self._token: headers['Authorization'] = f"token {self._token}"

        log.debug("Downloading %s", url)
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        result = response.json()
        self.issues.extend(result['items'])

        next_url = response.links['next']['url'] if 'next' in response.links else None
        if not next_url and result['total_count'] > 1000 and len(result['items']) > 0:
            # We hit the 1000-issue limit. Continue the search just beyond the last issue we got.
            next_url = GitHubIssues._search_url(f"{query}+created:>{result['items'][-1]['created_at']}")
        return next_url
