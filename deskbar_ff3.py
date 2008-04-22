import deskbar.core.Utils
from deskbar.core.BrowserMatch import BrowserMatch
import deskbar.interfaces.Module
import deskbar.interfaces.Match
from ConfigParser import RawConfigParser
from os.path import join, expanduser
from tempfile import mkdtemp
from shutil import copy, rmtree
import sqlite3

HANDLERS = ["Firefox3Module"]

# Taken from mozilla.py of deskbar-applet 2.20
def get_firefox_home_file(needed_file):
    firefox_dir = expanduser("~/.mozilla/firefox/")
    config = RawConfigParser({"Default" : 0})
    config.read(expanduser(join(firefox_dir, "profiles.ini")))
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
        return join(path, needed_file)

    return join(firefox_dir, path, needed_file)

def create_places_copy():
    """Create a copy of the places database, in a temporary directory. The
    caller is responsible to get rid of the directory and its contents when
    done."""
    tempdir = mkdtemp()
    copy(get_firefox_home_file("places.sqlite"),tempdir)
    return tempdir

QUERY="""
SELECT title, url FROM moz_places
WHERE title LIKE ? OR url LIKE ? OR url LIKE ? OR url LIKE ?
ORDER BY frecency DESC
LIMIT 10
"""

def ff3_query(str):
    dir = create_places_copy()
    conn = sqlite3.connect('%s/places.sqlite' % dir)
    c = conn.cursor()
    c.execute(QUERY, 
            ("%%%s%%" % str,                # For title match
                "%s%%" % str,               # For actual URL match
                "http://%s%%" % str,        # For protocol-less URL match
                "http://www.%s%%" % str,    # For www-less URL match
                ))
    result = c.fetchall()
    c.close()
    conn.close()
    rmtree(dir)
    return result

class Firefox3Module(deskbar.interfaces.Module):
    INFOS = {"icon": deskbar.core.Utils.load_icon("firefox-3.0.png"),
             "name": "Firefox 3 Places",
             "description": "Search Firefox 3 Places",
             "version" : "git",
    }

    def __init__ (self):
        deskbar.interfaces.Module.__init__ (self)

    def query (self, query):
        results = [BrowserMatch(name, url, is_history = True) \
                  for (name, url) in ff3_query(query)]
        self._emit_query_ready(query, results)
