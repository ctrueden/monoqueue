#!/usr/bin/env python
#
# This is free and unencumbered software released into the public domain.
# See the UNLICENSE file for details.
#
# ------------------------------------------------------------------------
# discourse.py
# ------------------------------------------------------------------------

"""
Routines to download and organize information from Discourse.

https://docs.discourse.org/#tag/Search/operation/search

curl -X GET https://forum.image.sc/c/development/5.json \
 -H "Api-Key: <your-key-here>" \
 -H "Api-Username: ctrueden" | tee result

curl -i -sS -X GET -G https://forum.image.sc/search.json \
  --data-urlencode 'q=#development tags:imagej,imagej2,fiji,scijava,scifio status:open status:unsolved' \ 
  --data-urlencode 'page=2' \
  -H "Api-Key: <your-key-here>" \
  -H "Api-Username: ctrueden" | tee image-sc-forum-search-page-2.json
"""

import json, sys, time

import requests

from .log import log


def update(mq, config):
    baseurl = config.get("baseurl", f"https://{config['source']}")
    username = config["username"]
    key = config["key"]
    query = config["query"]

    search = DiscourseSearch(baseurl=baseurl, username=username, key=key)
    search._progress = mq.progress
    search.download(query)

    for topic in search.topics:
        url = f"{baseurl}/t/{topic['id']}"
        if not url in mq.items:
            mq.items[url] = {}

        mq.items[url].update({
            "title": topic["title"],
            "created": topic["created_at"],
            "updated": topic["last_posted_at"],
            "topic": topic
        })


class DiscourseSearch:

    def __init__(self, baseurl, items=None, username=None, key=None):
        self._baseurl = baseurl
        self._username = username
        self._key = key
        self.topics = [] if items is None else items
        self._delay_per_request = 4
        self._max_requests = 100
        self._progress = None

    def load(self, filepath):
        """
        Load search data from the given JSON file.
        """
        with open(filepath) as f:
            result = json.loads(f.read())
            self.topics.update(result)

    def save(self, filepath):
        """
        Save search data to the given JSON file.
        """
        with open(filepath, 'w') as f:
            return json.dump(self.topics, f, sort_keys=True, indent=4)

    def download(self, query: str):
        """
        Download content from Discourse according to the given query.
        """
        url = f"{self._baseurl}/search.json"
        page = 1
        for _ in range(self._max_requests):
            more = self._download_page(url, query, page)
            if self._progress: self._progress(more)
            if not more: break
            page += 1
            time.sleep(self._delay_per_request)

    def _download_page(self, url: str, query: str, page: int):
        headers = {'User-Agent': 'monoqueue'}
        if self._key: headers['Api-Key'] = f"{self._key}"
        if self._username: headers['Api-Username'] = f"{self._username}"

        log.debug("Downloading %s page %d", url, page)
        params = {"q": query, "page": page}
        response = requests.get(url, params=params, headers=headers)
        response.raise_for_status()
        result = response.json()
        self.topics.extend(result['topics'])

        gsr = result.get("grouped_search_result", {})
        return gsr.get('more_full_page_results', False)
