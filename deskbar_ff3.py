#!/usr/bin/python

# Firefox 3 places lookup module
# Written by Ohad Lutzky <ohad@lutzky.net>
# Many thanks to Jeremy Cantrell <jmcantrell@gmail.com>

import os.path
import logging
logging.getLogger().name = os.path.splitext(os.path.basename(__file__))[0]

import urllib

import gtk
import shutil, sqlite3
import deskbar.core.Categories # Fix for circular Utils-Categories dependency
import deskbar.core.Utils
from deskbar.core.BrowserMatch import BrowserMatch, BrowserSmartMatch
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

class FirefoxSearchJson:
    def __init__(self, search_json_filename):
        import json
        json_file = open(search_json_filename, "r")
        json_data = json_file.read()
        json_file.close()
        data = json.read(json_data)
        self.engines = []

        for source, engine_data in data.items():
            if isinstance(engine_data, dict) and "engines" in engine_data:
                self.engines.extend(engine_data["engines"])

    def get_engine_urls(self, engine, suggestions = False):
        def is_suggestion(url):
            return "type" in url and url["type"] == "application/x-suggestions+json"

        return filter(lambda x: is_suggestion(x) == suggestions, engine["_urls"])

    def place_terms(self, s, query):
        _s = s
        for escape_sequence in ["{searchTerms}", "{SearchTerms}"]:
            _s = _s.replace(escape_sequence, query)
        return _s

    def param_list_to_dict(self, param_list, query):
        d = {}
        for param in param_list:
            # TODO some engines have trueValue, falseValue and a condition.
            # See google suggest.
            if "value" in param:
                d[param["name"]] = self.place_terms(param["value"], query)
        return d

    def searches_for(self, query, suggestions = False):
        for engine in [ x for x in self.engines if not x.get("hidden") ]:
            for url in self.get_engine_urls(engine, suggestions):
                if url["params"]:
                    param_string = "?%s" % \
                            urllib.urlencode( \
                            self.param_list_to_dict(url["params"], query) \
                            )
                else:
                    param_string = ""

                search_url = self.place_terms("%s%s" % (url["template"], \
                        param_string), query)

                yield (engine["_name"], search_url)

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
        self.json_searcher = FirefoxSearchJson(get_firefox_home_file('search.json'))
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

    def query_searches(self, query):
        return self.json_searcher.searches_for(query)

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

        matches += [
                BrowserSmartMatch(name=name, url=url,
                    bookmark=BrowserMatch(name,url))
                    for (name, url) in self.query_searches(query)
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
    import optparse

    parser = optparse.OptionParser("usage: %prog [options] [query]")
    parser.add_option("-v", "--verbose", dest="verbose",
            help="Increase verbosity", action="store_true", default=False)
    parser.add_option("--search-urls", dest="search_urls",
            help="Only show search URLs", action="store_true", default=False)
    parser.add_option("--places", dest="places",
            help="Only show places (URLs followed by names)",
            action="store_true", default=False)
    parser.add_option("--no-history", dest="history",
            help="Only show explicitly starred URLs", action="store_false",
            default=True)
    options, args = parser.parse_args()

    if options.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    if options.places and options.search_urls:
        parser.error("Please choose either --places or --search-urls "
            "(or neither)")

    if len(args) < 1:
        parser.error("No query string specified")

    logging.info("Deskbar FF3 at your service")
    querier = Firefox3Module()

    if options.search_urls:
        for name, url in list(querier.query_searches(sys.argv[-1])):
            print url, name
        sys.exit(0)

    if options.places:
        results = querier.query_places(args[0])
        for name, url, number, is_bookmarks in results:
            if options.history or is_bookmarks:
                if name:
                    print url, name
                else:
                    print url
        sys.exit(0)

    # Neither places or search urls were explicitly requested, print
    # everything.

    print "Searches:"
    for name, search_url in list(querier.query_searches(args[0])):
        print "   ", name, "-", search_url

    print ""

    print "Results:"
    results = querier.query_places(args[0])
    if not results:
        print "No results"
    else:
        for name, url, number, is_bookmark in results:
            if is_bookmark or options.history:
                display_form = "%s%s" % (
                        is_bookmark and "[*]" or "   ",
                        name and "%s - %s" % (name, url) or url
                        )

                print display_form
