import deskbar.core.Utils
from deskbar.core.BrowserMatch import BrowserMatch
import deskbar.interfaces.Module
import deskbar.interfaces.Match

import sys
from os.path import expanduser
sys.path.append(expanduser('~/.gnome2/deskbar-applet/modules-2.20-compatible/'))
import ff3

HANDLERS = ["Firefox3Module"]

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
                  for (name, url) in ff3.query(query)]
        self._emit_query_ready(query, results)
