#!/usr/bin/python

# Firefox 3 places lookup module
# Written by Ohad Lutzky <ohad@lutzky.net>
# Many thanks to Jeremy Cantrell <jmcantrell@gmail.com>

import os.path
import logging
logging.getLogger().name = os.path.splitext(os.path.basename(__file__))[0]

import shutil, sqlite3
import deskbar.core.Categories # Fix for circular Utils-Categories dependency
import deskbar.core.Utils
from deskbar.core.BrowserMatch import BrowserMatch
import deskbar.interfaces.Module
import deskbar.interfaces.Match
from ConfigParser import RawConfigParser

HANDLERS = ["Firefox3Module"]

# Taken from mozilla.py of deskbar-applet 2.20
def get_firefox_home_file(needed_file):
    firefox_dir = os.path.expanduser("~/.mozilla/firefox/")
    config = RawConfigParser({"Default" : 0})
    config.read(os.path.expanduser(os.path.join(firefox_dir, "profiles.ini")))
    path = None

    for section in config.sections():
        if config.has_option(section, "Default") and config.get(section, "Default") == "1":
            path = config.get (section, "Path")
            break
        elif path == None and config.has_option(section, "Path"):
            path = config.get (section, "Path")

    if path == None:
        return ""

    if path.startswith("/"):
        return os.path.join(path, needed_file)

    return os.path.join(firefox_dir, path, needed_file)

QUERY_BASE="""
select
    ifnull(b.title,p.title), /* If we have a bookmark title, use it */
    p.url,
    p.frecency

from
    moz_places p left join
    moz_bookmarks b on b.fk = p.id

where
    (
        p.hidden = 0
        and
        (
            (
                %(url_likeness)s
            )
            or
            (
                %(title_likeness)s
            )
        )
    )

    or

    (
        %(tag_matches)s
    )

group by p.id
order by frecency desc
limit 10;
"""

TAG_SUBQUERY="""
p.id in (
    select
    b.fk
    from
    moz_bookmarks tag inner join
    moz_bookmarks b on tag.id = b.parent
    where
    tag.parent = 4 and /* tag is actually a tag, 4 is the root of all tags */
    tag.title like ?
)
"""

def construct_query(keywords):
    """Construct a query for the given keywords. The query should return any
    places with tags matching ALL keywords, in addition to any places whose
    URL or title matches ALL keywords."""

    result = QUERY_BASE % {
            "url_likeness" : " and ".join("p.url like ?" for k in keywords),
            "title_likeness" : " and ".join("ifnull(b.title, p.title) like ?" for k in keywords),
            "tag_matches" : " and ".join(TAG_SUBQUERY for k in keywords),
            }
    logging.debug("Preparing query:\n%s", result)

    return result

class Firefox3Module(deskbar.interfaces.Module):
    INFOS = {
            "icon": deskbar.core.Utils.load_icon("firefox-3.0.png"),
            "name": "Firefox 3 Places",
            "description": "Search Firefox 3 Places",
            "version": "git",
            }

    @staticmethod
    def has_requirements():
        if os.path.isfile(get_firefox_home_file('places.sqlite')):
            return True
        else:
            Firefox3Module.INSTRUCTIONS = "Firefox 3 must be used (places DB not found)"
            return False

    def __init__(self):
        deskbar.interfaces.Module.__init__(self)
        logging.debug("Initializing %s", __file__)
        self.places_db = get_firefox_home_file('places.sqlite')
        self.places_db_copy = os.path.join(os.path.dirname(__file__), 'deskbar_ff3.sqlite')
        logging.debug("My Places DB is at %s", self.places_db)
        logging.debug("My Places DB copy is at %s", self.places_db_copy)
        self.copy_places_db()

    def copy_places_db(self):
        # Copying a locked database should still yield a valid database
        # for us to work with, so there is no reason to check for the lock
        shutil.copy(self.places_db, self.places_db_copy)

    def is_db_copy_stale(self):
        if not os.path.isfile(self.places_db_copy):
            return True
        else:
            mtime = os.path.getmtime(self.places_db)
            mtime_copy = os.path.getmtime(self.places_db_copy)
            if mtime > mtime_copy: return True

        return False

    def refresh_places_db(self, force = False):
        if force or self.is_db_copy_stale():
            logging.debug("Refreshing places DB copy")
            self.copy_places_db()

    def query_places(self, query):
        self.refresh_places_db()
        conn = sqlite3.connect(self.places_db_copy)
        c = conn.cursor()
        keywords = [ "%%%s%%" % keyword for keyword in query.split() ]
        query = construct_query(keywords)

        logging.debug("Executing query with keywords %s", keywords)
        c.execute(query, tuple(keywords * 3))
        r = c.fetchall()
        c.close()
        conn.close()
        return r

    def query(self, query):
        results = self.query_places(query)
        # if query didn't work, don't notify deskbar
        if not results: return

        # If our match has a name, display it and the url. Otherwise, just
        # the URL.
        matches = [
                BrowserMatch(name and ("%s - %s" % (name, url))
                    or url, url)
                    for (name, url, frecency) in results
                    ]

        self._emit_query_ready(query, matches)

if __name__ == '__main__':
    import sys
    if "-v" in sys.argv:
        logging.getLogger().setLevel(logging.DEBUG)
        sys.argv.remove("-v")

    if len(sys.argv) < 2:
        print "Usage: %s [query]" % __file__
        sys.exit(1)

    logging.info("Deskbar FF3 at your service")
    querier = Firefox3Module()
    print "Results:"
    results = querier.query_places(sys.argv[-1])
    if not results:
        print "No results"
    else:
        for name, url, number in results:
            if name:
                print name, "-", url
            else:
                print url
