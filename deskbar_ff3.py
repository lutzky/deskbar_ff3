#!/usr/bin/python

# Firefox 3 places lookup module
# Written by Ohad Lutzky <ohad@lutzky.net>
# Many thanks to Jeremy Cantrell <jmcantrell@gmail.com>

import os.path
import logging
logging.getLogger().name = os.path.splitext(os.path.basename(__file__))[0]

import gtk
import shutil, sqlite3
import deskbar.core.Categories # Fix for circular Utils-Categories dependency
import deskbar.core.Utils
from deskbar.core.BrowserMatch import BrowserMatch
from deskbar.core.GconfStore import GconfStore
import deskbar.interfaces.Module
import deskbar.interfaces.Match
from ConfigParser import RawConfigParser

HANDLERS = ["Firefox3Module"]
GCONF_INCLUDE_URL_KEY = GconfStore.GCONF_DIR + '/deskbar_ff3/include_url'
GCONF_MAX_RESULTS_KEY = GconfStore.GCONF_DIR + '/deskbar_ff3/max_results'

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

QUERY_FOLDERS = """
    select
        b.title the_title,
        p.url the_url,
        p.frecency the_frecency,
        b.id is not NULL is_bookmark
    from
        moz_bookmarks f inner join
        moz_bookmarks fb on f.id = fb.parent inner join
        moz_bookmarks b on fb.fk = b.fk inner join
        moz_places p on b.fk = p.id
    where
        length(b.title) > 0 and
        length(p.rev_host) > 0 and
        f.type = 2 and
        p.hidden = 0 and
        %s
"""

QUERY_URLS = """
    select
        coalesce(b.title, p.title) the_title,
        p.url the_url,
        p.frecency the_frecency,
        b.id is not NULL is_bookmark
    from
        moz_places p left outer join
        moz_bookmarks b on p.id = b.fk left outer join
        moz_bookmarks bp on bp.id = b.parent
    where
        length(p.rev_host) > 0 and
        (bp.parent <> 4 or b.id is null) and
        p.hidden = 0 and
        %s
"""

QUERY_TITLES = """
    select
        coalesce(b.title, p.title) the_title,
        p.url the_url,
        p.frecency the_frecency,
        b.id is not NULL is_bookmark
    from
        moz_places p left outer join
        moz_bookmarks b on p.id = b.fk left outer join
        moz_bookmarks bp on bp.id = b.parent
    where
        length(the_title) > 0 and
        length(p.rev_host) > 0 and
        (bp.parent <> 4 or b.id is null) and
        p.hidden = 0 and
        %s
"""

QUERY_TAGS = """
    select
        coalesce(b.title, p.title) the_title,
        p.url the_url,
        p.frecency the_frecency,
        b.id is not NULL is_bookmark
    from
        moz_bookmarks t inner join
        moz_bookmarks tb on t.id = tb.parent inner join
        moz_bookmarks b on b.fk = tb.fk inner join
        moz_bookmarks bp on b.parent = bp.id inner join
        moz_places p on b.fk = p.id
    where
        length(p.rev_host) > 0 and
        (bp.parent <> 4 or b.id is null) and
        t.parent = 4 and
        p.hidden = 0 and
        %s
"""


class Config(object):

    def __init__(self):
        self.gconf_client = GconfStore.get_instance().get_client()

    def _get_include_url(self):
        value = self.gconf_client.get_bool(GCONF_INCLUDE_URL_KEY)
        if value is None: value = True
        return value

    def _set_include_url(self, value):
        self.gconf_client.set_bool(GCONF_INCLUDE_URL_KEY, value)

    include_url = property(_get_include_url, _set_include_url)

    def _get_max_results(self):
        value = self.gconf_client.get_int(GCONF_MAX_RESULTS_KEY)
        if not value: value = 10
        return value

    def _set_max_results(self, value):
        self.gconf_client.set_int(GCONF_MAX_RESULTS_KEY, value)

    max_results = property(_get_max_results, _set_max_results)


class PreferencesDialog(gtk.Dialog):

    def __init__(self, parent, config):
        gtk.Dialog.__init__(self, "Mozilla Places Preferences", parent,
                gtk.DIALOG_DESTROY_WITH_PARENT, (gtk.STOCK_CLOSE, gtk.RESPONSE_CLOSE))
        self.config = config
        cb = gtk.CheckButton("Include URL in Result?")
        cb.connect("toggled", self._on_include_url_toggled)
        cb.set_active(self.config.include_url)
        self.vbox.pack_start(cb)
        hbox = gtk.HBox()
        hbox.pack_start(gtk.Label('Maximum Results:'))
        sb = gtk.SpinButton(gtk.Adjustment(self.config.max_results, 1, 20, 1, 1))
        sb.set_numeric(True)
        sb.connect("value-changed", self._on_max_results_value_changed)
        hbox.pack_start(sb)
        self.vbox.pack_start(hbox)
        self.show_all()

    def _on_include_url_toggled(self, widget):
        self.config.include_url = widget.get_active()

    def _on_max_results_value_changed(self, widget):
        self.config.max_results = widget.get_value_as_int()


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
        self.config = Config()

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
        query = self.construct_query(keywords)
        logging.debug("Executing query with keywords %s", keywords)
        c.execute(query, tuple(keywords * 4))
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

        def result_title(name, url):
            if not name:
                return url
            if self.config.include_url:
                return "%s - %s" % (name, url)
            return name

        matches = [
                BrowserMatch(result_title(name, url), url,
                                is_history = not is_bookmark)
                for name, url, frecency, is_bookmark in results
                ]

        self._emit_query_ready(query, matches)

    def has_config(self):
        return True

    def show_config(self, parent):
        dialog = PreferencesDialog(parent, self.config)
        dialog.run()
        dialog.destroy()

    def construct_query(self, keywords):
        """Construct a query for the given keywords. The query should return any
        places with tags matching ALL keywords, in addition to any places whose
        URL or title matches ALL keywords."""

        queries = [
                QUERY_FOLDERS % ' and '.join('f.title like ?' for k in keywords),
                QUERY_URLS % ' and '.join('p.url like ?' for k in keywords),
                QUERY_TITLES % ' and '.join('the_title like ?' for k in keywords),
                QUERY_TAGS % ' and '.join('t.title like ?' for k in keywords)
                ]

        orderby = " order by the_frecency desc, the_title"
        limit = 'limit %s' % self.config.max_results
        result = ' '.join([' union '.join(queries), orderby, limit]) + ';'
        logging.debug("Preparing query:\n%s", result)

        return result


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
        for name, url, number, is_bookmark in results:
            if is_bookmark:
                print "[*]",
            else:
                print "   ",

            if name:
                print name, "-", url
            else:
                print url
