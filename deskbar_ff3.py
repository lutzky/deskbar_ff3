import deskbar.core.Utils
from deskbar.core.BrowserMatch import BrowserMatch
import deskbar.interfaces.Module
import deskbar.interfaces.Match
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
        self._emit_query_ready(query, 
		[BrowserMatch(name, url) for (name, url) in ff3.query(query)]
		)
