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

QUERY="""
    select
        b.title,
        p.url,
        p.frecency
    from
        moz_bookmarks b inner join
        moz_places p on b.fk = p.id
    where
        b.title like ? and
        b.parent in (2,3,5)

    union

    select
        b.title,
        p.url,
        p.frecency
    from
        moz_places p inner join
        moz_bookmarks b on p.id = b.fk
    where
        b.parent in (2,3,5) and
        p.url like ? and
        p.hidden = 0

    union

    select
        b.title title,
        p.url url,
        p.frecency frecency
    from
        moz_bookmarks b inner join
        moz_places p on b.fk = p.id
    where
        b.parent in (1,2,3,4,5) and
        b.fk in (
            select
                p.id
            from
                moz_bookmarks t inner join
                moz_bookmarks b on t.id = b.parent inner join
                moz_places p on b.fk = p.id
            where
                t.parent = 4 and
                t.title like ?
        )

    order by
        frecency desc

    limit 10
"""

class Firefox3Module(deskbar.interfaces.Module):

    INFOS = {
            "icon": deskbar.core.Utils.load_icon("firefox-3.0.png"),
            "name": "Firefox 3 Places",
            "description": "Search Firefox 3 Places",
            "version": "git",
            }

    def __init__(self):
        deskbar.interfaces.Module.__init__(self)
        logging.debug("Initializing %s", __file__)
        self.places_db = get_firefox_home_file('places.sqlite')
        self.places_db_copy = os.path.join(os.path.dirname(__file__), 'deskbar_ff3.sqlite')
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
        q = "%%%s%%" % query
        logging.debug("Executing query with parameter %s", q)
        c.execute(QUERY, (q, q, q))
        r = c.fetchall()
        c.close()
        conn.close()
        return r

    def query(self, query):
        results = self.query_places(query)
        # if query didn't work, don't notify deskbar
        if not results: return
        self._emit_query_ready(query, [BrowserMatch(name, url) for (name, url, frecency) in results])

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
            print name
