import os.path, shutil, tempfile, sqlite3
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
        b.title,
        p.url,
        p.frecency
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
        p.frecency desc

    limit 10
    """

class Firefox3Module(deskbar.interfaces.Module):

    INFOS = {
            "icon": deskbar.core.Utils.load_icon("firefox-3.0.png"),
            "name": "Firefox 3 Places",
            "description": "Search Firefox 3 Places",
            "version": "git-jmc",
            }

    def initialize(self):
        self.tempdir = tempfile.mkdtemp()
        self.places_db_fn = get_firefox_home_file('places.sqlite')
        self.places_db_mtime = 0
        self.places_db_conn = None

    def stop(self):
        self.places_db_conn.close()
        shutil.rmtree(self.tempdir)

    def get_cursor(self):
        mtime = os.path.getmtime(self.places_db_fn)
        if mtime > self.places_db_mtime:
            shutil.copy(self.places_db_fn, self.tempdir)
            if self.places_db_conn: self.places_db_conn.close()
            self.places_db_conn = sqlite3.connect(os.path.join(self.tempdir, os.path.basename(self.places_db_fn)))
            self.places_db_mtime = mtime
        return self.places_db_conn.cursor()

    def query_places(self, query):
        c = self.get_cursor()
        q = "%%%s%%" % query
        c.execute(QUERY, (q, q, q))
        r = c.fetchall()
        c.close()
        return r

    def query(self, query):
        results = [BrowserMatch(name, url) for (name, url, frecency) in self.query_places(query)]
        self._emit_query_ready(query, results)
