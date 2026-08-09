import sys

import xbmcaddon
import xbmcplugin

if __name__ == '__main__':
    xbmcaddon.Addon().openSettings()
    handle = int(sys.argv[1]) if len(sys.argv) > 1 else -1
    xbmcplugin.endOfDirectory(handle, succeeded=False, updateListing=False, cacheToDisc=False)
