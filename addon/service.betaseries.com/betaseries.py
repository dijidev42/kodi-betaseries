# -*- coding: utf-8 -*-
#
#  This Program is free software; you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation; either version 2, or (at your option)
#  any later version.
#
#  This Program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with XBMC; see the file COPYING.  If not, write to the
#  Free Software Foundation, 675 Mass Ave, Cambridge, MA 02139, USA.
#
#  code structure and portions of code based on service.scrobbler.librefm by Team-XBMC

import urllib.request, urllib.parse, urllib.error, socket, hashlib, time, platform
import xbmc, xbmcaddon
import simplejson as json

__addon__        = xbmcaddon.Addon()
__addonid__      = __addon__.getAddonInfo('id')
__addonname__    = __addon__.getAddonInfo('name')
__addonversion__ = __addon__.getAddonInfo('version')
__icon__         = __addon__.getAddonInfo('icon')
__platform__     = platform.system() + " " + platform.release()
__language__     = __addon__.getLocalizedString

socket.setdefaulttimeout(10)

def log(txt, loglevel=xbmc.LOGDEBUG):
    message = '%s: %s' % (__addonid__, txt)
    xbmc.log(msg=message, level=loglevel)

def set_user_agent():
    json_query = json.loads(xbmc.executeJSONRPC(
        '{ "jsonrpc": "2.0", "method": "Application.GetProperties", "params": {"properties": ["version", "name"]}, "id": 1 }'
    ))
    try:
        major = str(json_query['result']['version']['major'])
        minor = str(json_query['result']['version']['minor'])
        name = "Kodi" if int(major) >= 14 else "XBMC"
        version = "%s %s.%s" % (name, major, minor)
    except:
        log("could not get app version")
        version = "XBMC"
    return "Mozilla/5.0 (compatible; " + __platform__ + "; " + version + "; " + __addonid__ + "/" + __addonversion__ + ")"

def get_urldata(url, urldata, method):
    handler = urllib.request.HTTPSHandler()
    opener = urllib.request.build_opener(handler)
    body = None if urldata == '' else urllib.parse.urlencode(urldata).encode("utf-8")
    req = urllib.request.Request(url, data=body)
    req.add_header('Accept', 'application/json')
    req.add_header('User-Agent', __useragent__)
    req.get_method = lambda: method
    log('fetching URL: %s - data: %s - method: %s' % (url, body, method))
    try:
        connection = opener.open(req)
    except urllib.error.HTTPError as e:
        connection = e

    if connection.code:
        return connection.read()

    log('response empty')
    return 0

class Main:
    def __init__(self):
        self._service_setup()
        monitor = xbmc.Monitor()
        while not monitor.abortRequested():
            if monitor.waitForAbort(1):
                break

    def _service_setup(self):
        self.apikey       = 'cca540f2c2c4'
        self.apiurl       = 'https://api.betaseries.com'
        self.apiver       = '2.2'
        self.Monitor      = MyMonitor(action=self._get_settings)
        self._get_settings()

    def _get_settings(self):
        log('reading settings')
        service = []
        BetaActive = __addon__.getSetting('betaactive') == 'true'
        BetaFirst  = __addon__.getSetting('betafirst') == 'true'
        BetaUser   = __addon__.getSetting('betauser')
        BetaPass   = __addon__.getSetting('betapass').encode('utf-8')
        BetaBulk   = __addon__.getSetting('betabulk') == 'true'
        BetaMark   = __addon__.getSetting('betamark') == 'true'
        BetaUnMark = __addon__.getSetting('betaunmark') == 'true'
        BetaFollow = __addon__.getSetting('betafollow') == 'true'
        BetaNotify = __addon__.getSetting('betanotify') == 'true'

        if BetaActive and BetaUser and BetaPass:
            service = [
                'betaseries', self.apiurl, self.apikey, BetaUser, BetaPass,
                BetaFirst, '', False, 0, 0, 0,
                BetaBulk, BetaMark, BetaUnMark, BetaFollow, BetaNotify
            ]
            self.Player = MyPlayer(action=self._service_betaserie, service=service)
            if service[15]:
                xbmc.executebuiltin('Notification(%s,%s,%s,%s)' % (__addonname__, __language__(30003), 750, __icon__))

    def _service_betaserie(self, episode, service):
        tstamp = int(time.time())
        if not service[7]:
            if not service[6]:
                service = self._service_authenticate(service, str(tstamp))
            if service[6] and episode[0] and episode[1]:
                if not service[5] or (service[5] and episode[2] <= 1):
                    service = self._service_mark(service, episode)

    def _service_authenticate(self, service, timestamp):
        if service[10] > int(timestamp):
            return service

        md5pass = hashlib.md5()
        md5pass.update(service[4])
        url = service[1] + '/members/auth'
        urldata = {'v': self.apiver, 'key': service[2], 'login': service[3], 'password': md5pass.hexdigest()}

        try:
            response = get_urldata(url, urldata, "POST")
            data = json.loads(response)
            log('successfully authenticated')
        except:
            service = self._service_fail(service, True)
            xbmc.executebuiltin('Notification(%s,%s,%s,%s)' % (__addonname__, __language__(32003), 750, __icon__))
            log('failed to connect for authentication', xbmc.LOGINFO)
            return service

        if 'token' in data:
            service[6] = str(data['token'])
            service[8] = 0
            service[9] = 0
            service[10] = 0

        if data.get('errors'):
            log("%s error %s : %s" % (service[0], data['errors'][0]['code'], data['errors'][0]['text']), xbmc.LOGINFO)
            if data['errors'][0]['code'] < 2000:
                xbmc.executebuiltin('Notification(%s,%s,%s,%s)' % (__addonname__, __language__(32002), 750, __icon__))
                log('bad API usage', xbmc.LOGINFO)
                __addon__.setSetting('betaactive', 'false')
            elif data['errors'][0]['code'] > 4001:
                xbmc.executebuiltin('Notification(%s,%s,%s,%s)' % (__addonname__, __language__(32004), 750, __icon__))
                log('login or password incorrect', xbmc.LOGINFO)
                service[7] = True
            else:
                service = self._service_fail(service, True)
                xbmc.executebuiltin('Notification(%s,%s,%s,%s)' % (__addonname__, __language__(32001), 750, __icon__))
                log('server error while authenticating', xbmc.LOGINFO)
        return service

    def _service_mark(self, service, episode):
        log('marking item: %s' % (episode))

        if not service[12] and episode[2] > 0 and not episode[3]:
            log("abort marking, as play = %s" % episode[3])
            return service
        elif not service[13] and episode[2] == 0 and not episode[3]:
            log("abort unmarking, as play = %s" % episode[3])
            return service

        if episode[6] == 'episode':
            if service[14] and episode[2] != -1:
                url = service[1] + "/shows/show"
                urldata = {'v': self.apiver, 'key': service[2], 'token': service[6], 'thetvdb_id': episode[0]}
                try:
                    response = get_urldata(url, urldata, "POST")
                    data = json.loads(response)
                except:
                    service = self._service_fail(service, False)
                    log('failed to follow show %s' % episode[4], xbmc.LOGINFO)
                    return service

                if data.get('errors'):
                    log("%s error : %s %s" % (service[0], data['errors'][0]['code'], data['errors'][0]['text']), xbmc.LOGINFO)
                    if data['errors'][0]['code'] == 2001:
                        service[6] = ''
                        log('bad token while following show', xbmc.LOGINFO)
                        return service
                    elif data['errors'][0]['code'] == 2003:
                        log('already following show %s' % episode[4])
                    else:
                        xbmc.executebuiltin('Notification(%s,%s,%s,%s)' % (__addonname__, __language__(32005) + episode[4], 750, __icon__))
                        log('failed to follow show %s' % episode[4], xbmc.LOGINFO)
                        return service
                else:
                    if service[15]:
                        xbmc.executebuiltin('Notification(%s,%s,%s,%s)' % (__addonname__, __language__(30013) + episode[4], 750, __icon__))
                    log('now following show %s' % episode[4])

        if episode[6] == 'movie':
            url = service[1] + "/movies/movie"
            urldata = {'v': self.apiver, 'key': service[2], 'token': service[6], 'id': episode[0], 'state': episode[2]}
            method = "POST"
            if episode[2] == 0:
                act = "not watched"
                actlang = 30017
            else:
                act = "watched"
                actlang = 30016
        else:
            urldata = {'v': self.apiver, 'key': service[2], 'token': service[6], 'thetvdb_id': episode[1]}
            if service[11]:
                urldata.update({'bulk': 1})
            if episode[2] == 0:
                url = service[1] + "/episodes/watched"
                method = "DELETE"
                act = "not watched"
                actlang = 30015
            elif episode[2] == -1:
                url = service[1] + "/episodes/downloaded"
                method = "POST"
                act = "downloaded"
                actlang = 30101
            else:
                url = service[1] + "/episodes/watched"
                method = "POST"
                act = "watched"
                actlang = 30014

        try:
            response = get_urldata(url, urldata, method)
            data = json.loads(response)
        except:
            service = self._service_fail(service, False)
            log('failed to mark as %s' % act, xbmc.LOGINFO)
            return service

        if data.get('errors'):
            log("%s error : %s %s" % (service[0], data['errors'][0]['code'], data['errors'][0]['text']), xbmc.LOGINFO)
            if data['errors'][0]['code'] == 2001:
                service[6] = ''
                log('bad token while marking %s' % episode[6], xbmc.LOGINFO)
            elif data['errors'][0]['code'] == 0:
                if episode[6] == 'movie':
                    log('%s already marked as %s' % (episode[5], act), xbmc.LOGINFO)
                else:
                    log('not following show, or %s %s already marked as %s' % (episode[6], episode[5], act), xbmc.LOGINFO)
            else:
                if episode[6] == 'movie':
                    actlang = 32007
                else:
                    actlang = 32006
                xbmc.executebuiltin('Notification(%s,%s,%s,%s)' % (__addonname__, __language__(actlang), 750, __icon__))
                log('error marking %s %s as %s' % (episode[6], episode[5], act), xbmc.LOGINFO)
        else:
            if service[15]:
                xbmc.executebuiltin('Notification(%s,%s,%s,%s)' % (__addonname__, __language__(actlang), 750, __icon__))
            log('%s %s %s marked as %s' % (episode[4], episode[6], episode[5], act))

        return service

    def _service_fail(self, service, timer):
        timestamp = int(time.time())
        service[8] += 1
        if service[8] > 2:
            service[6] = ''
        if timer:
            if service[9] == 0 or service[9] == 7680:
                service[9] = 60
            else:
                service[9] = 2 * service[9]
        service[10] = timestamp + service[9]
        return service

class MyPlayer(xbmc.Monitor):
    def __init__(self, *args, **kwargs):
        xbmc.Monitor.__init__(self)
        self.action = kwargs['action']
        self.service = kwargs['service']
        self.Play = False
        log('Player Class Init')
        self.ScanRecentlyadded()

    def _norm(self, value):
        if value is None:
            return ''
        return str(value).strip().lower()

    def _safe_int_year(self, value):
        try:
            if value is None or value == '':
                return None
            return int(str(value)[:4])
        except:
            return None

    def _pick_best_show(self, shows, showtitle, year=None):
        if not shows:
            return None

        wanted = self._norm(showtitle)
        best = None
        best_score = -9999

        for show in shows:
            score = 0
            title = self._norm(show.get('title'))
            original_title = self._norm(show.get('original_title'))
            slug = self._norm(show.get('slug'))

            for candidate in [title, original_title, slug]:
                if not candidate:
                    continue
                if candidate == wanted:
                    score += 120
                elif wanted in candidate or candidate in wanted:
                    score += 40

            show_year = self._safe_int_year(show.get('creation') or show.get('release_date') or show.get('year'))
            if year and show_year:
                if show_year == year:
                    score += 80
                elif abs(show_year - year) == 1:
                    score += 25

            if score > best_score:
                best_score = score
                best = show

        log("best show match for '%s' (%s): %s score=%s" % (
            showtitle, year, best.get('title') if best else 'None', best_score
        ))
        return best

    def _pick_best_movie(self, movies, movietitle, year=None):
        if not movies:
            return None

        wanted = self._norm(movietitle)
        best = None
        best_score = -9999

        for movie in movies:
            score = 0
            title = self._norm(movie.get('title'))
            original_title = self._norm(movie.get('original_title'))

            for candidate in [title, original_title]:
                if not candidate:
                    continue
                if candidate == wanted:
                    score += 120
                elif wanted in candidate or candidate in wanted:
                    score += 40

            movie_year = self._safe_int_year(movie.get('production_year') or movie.get('release_date') or movie.get('year'))
            if year and movie_year:
                if movie_year == year:
                    score += 80
                elif abs(movie_year - year) == 1:
                    score += 25

            if score > best_score:
                best_score = score
                best = movie

        log("best movie match for '%s' (%s): %s score=%s" % (
            movietitle, year, best.get('title') if best else 'None', best_score
        ))
        return best

    def onNotification(self, sender, method, data):
        if sender != 'xbmc':
            return

        if method == 'VideoLibrary.OnScanFinished':
            self.ScanRecentlyadded()

        elif method == 'Player.OnPlay':
            result = json.loads(data)
            if 'item' in result and 'id' in result['item']:
                if result['item']['type'] == 'episode':
                    xbmc.sleep(1000)
                    log("watching episode, library id = %s" % result['item']['id'])
                    self.Play = True
                elif result['item']['type'] == 'movie':
                    xbmc.sleep(1000)
                    log("watching movie, library id = %s" % result['item']['id'])
                    self.Play = True

        elif method == 'Player.OnStop':
            result = json.loads(data)
            if 'item' in result and 'title' in result["item"] and 'id' in result['item'] and result.get("end"):
                if result['item']['type'] == 'episode':
                    try:
                        scraper_url = "%s/episodes/scraper?file=%s&key=%s" % (self.service[1], result["item"]["title"], self.service[2])
                        scraper_data = json.loads(get_urldata(scraper_url, "", "GET"))["episode"]
                        title = str(scraper_data["season"]) + "x" + str(scraper_data["episode"])
                        show_url = "%s/shows/display?id=%s&key=%s" % (self.service[1], scraper_data["show_id"], self.service[2])
                        tvdbid = json.loads(get_urldata(show_url, "", "GET"))["show"]["thetvdb_id"]
                        episode = [int(tvdbid), int(scraper_data["thetvdb_id"]), 1, True, str(scraper_data["show_title"]), title, 'episode']
                        self.action(episode, self.service)
                    except:
                        log("failed to resolve episode from scraper endpoint", xbmc.LOGINFO)

                elif result['item']['type'] == 'movie':
                    try:
                        scraper_url = "%s/movies/scraper?file=%s&key=%s" % (self.service[1], result["item"]["title"], self.service[2])
                        scraper_data = json.loads(get_urldata(scraper_url, "", "GET"))["movie"]
                        movie = [int(scraper_data["id"]), int(scraper_data.get("thetvdb_id", 0) or 0), 1, True, '', str(scraper_data["title"]), 'movie']
                        self.action(movie, self.service)
                    except:
                        log("failed to resolve movie from scraper endpoint", xbmc.LOGINFO)
            else:
                xbmc.sleep(1000)

            self.Play = False

        elif method == 'VideoLibrary.OnUpdate':
            result = json.loads(data)
            if 'playcount' in result and 'item' in result:
                if result['item']['type'] == 'episode':
                    log("episode status changed for library id = %s, playcount = %s" % (result['item']['id'], result['playcount']))
                    episode = self._get_episode_info(result['item']['id'], result['playcount'], self.Play)
                    if episode:
                        self.action(episode, self.service)
                        self.Play = False
                        if result['playcount'] == 0:
                            episode[2] = -1
                            self.action(episode, self.service)

                elif result['item']['type'] == 'movie':
                    log("movie status changed for library id = %s, playcount = %s" % (result['item']['id'], result['playcount']))
                    movie = self._get_movie_info(result['item']['id'], result['playcount'], self.Play)
                    if movie:
                        self.action(movie, self.service)
                        self.Play = False

    def ScanRecentlyadded(self):
        f = __addon__.getAddonInfo('path') + '/lastdate.tmp'
        try:
            with open(f, "r") as fic:
                lastdate = fic.read()
        except:
            lastdate = '2001-01-01 00:00:00'

        newdate = lastdate
        result_episodes = json.loads(xbmc.executeJSONRPC(
            '{ "jsonrpc": "2.0", "method": "VideoLibrary.GetRecentlyAddedEpisodes", "params": {"properties": ["dateadded"]}, "id": 1 }'
        ))

        if 'result' in result_episodes:
            for episode in result_episodes['result']['episodes']:
                if episode['dateadded'] > lastdate:
                    if episode['dateadded'] > newdate:
                        newdate = episode['dateadded']
                    log("%s with id %s has been added %s" % (episode['label'], episode['episodeid'], episode['dateadded']))
                    episode = self._get_episode_info(episode['episodeid'], -1, self.Play)
                    if episode and type(episode) is list:
                        episode[2] = -1
                        self.action(episode, self.service)

            with open(f, 'wb') as fic:
                fic.write(newdate.encode('utf-8'))
        else:
            log("VideoLibrary GetRecentlyAddedEpisodes ERROR : %s" % result_episodes)

    def _get_episode_info(self, episodeid, playcount, playstatus):
        showtitle = ''
        season = None
        episode_num = None
        show_year = None
        tvdbid = ''
        tvdbepid = ''

        try:
            q = '{"jsonrpc":"2.0","method":"VideoLibrary.GetEpisodeDetails","params":{"episodeid":%d,"properties":["tvshowid","showtitle","season","episode","uniqueid"]},"id":1}' % episodeid
            ep = json.loads(xbmc.executeJSONRPC(q))['result']['episodedetails']
            showtitle = ep.get('showtitle', '')
            season = ep.get('season')
            episode_num = ep.get('episode')
            tvshowid = ep.get('tvshowid')

            if tvshowid is not None:
                q2 = '{"jsonrpc":"2.0","method":"VideoLibrary.GetTVShowDetails","params":{"tvshowid":%d,"properties":["year","title","originaltitle","uniqueid"]},"id":1}' % tvshowid
                show = json.loads(xbmc.executeJSONRPC(q2))['result']['tvshowdetails']
                show_year = show.get('year')
                show_uniqueid = show.get('uniqueid', {}) or {}
                tvdbid = show_uniqueid.get('tvdb') or show_uniqueid.get('thetvdb') or ''
                if not showtitle:
                    showtitle = show.get('title') or show.get('originaltitle') or ''
        except:
            log("could not get episode details", xbmc.LOGINFO)
            return False

        if not showtitle or season is None or episode_num is None:
            return False

        if not tvdbid:
            url = self.service[1] + '/shows/search'
            urldata = '?v=2.2&key=' + self.service[2] + '&title=' + urllib.parse.quote(showtitle)
            try:
                data = json.loads(get_urldata(url + urldata, '', "GET"))
                best = self._pick_best_show(data.get('shows', []), showtitle, self._safe_int_year(show_year))
                if best:
                    tvdbid = best.get('thetvdb_id')
            except:
                log("could not fetch tvshow's thetvdb_id", xbmc.LOGINFO)
                return False

        if not tvdbid:
            log("could not fetch tvshow's thetvdb_id", xbmc.LOGINFO)
            return False

        url = self.service[1] + '/shows/episodes'
        urldata = '?v=2.2&key=' + self.service[2] + '&thetvdb_id=' + str(tvdbid) + '&season=' + str(season) + '&episode=' + str(episode_num)
        try:
            data = json.loads(get_urldata(url + urldata, '', "GET"))
            episodes = data.get('episodes', [])
            if episodes:
                tvdbepid = episodes[0].get('thetvdb_id')
        except:
            log("could not fetch episode's thetvdb_id", xbmc.LOGINFO)
            return False

        if not tvdbepid:
            log("could not fetch episode's thetvdb_id for %s S%02dE%02d" % (showtitle, season, episode_num), xbmc.LOGINFO)
            return False

        epname = str(season) + 'x' + str(episode_num)
        return [int(tvdbid), int(tvdbepid), int(playcount), bool(playstatus), showtitle, epname, 'episode']
    
    def _get_movie_info(self, movieid, playcount, playstatus):
        try:
            q = '{"jsonrpc":"2.0","method":"VideoLibrary.GetMovieDetails","params":{"movieid":%d,"properties":["title","originaltitle","imdbnumber","uniqueid","year"]},"id":1}' % movieid
            movie = json.loads(xbmc.executeJSONRPC(q))['result']['moviedetails']
        except:
            log("could not get movie details", xbmc.LOGINFO)
            return False

        uniqueid = movie.get('uniqueid', {}) or {}
        imdbid = uniqueid.get('imdb') or movie.get('imdbnumber') or ''
        tmdbid = uniqueid.get('tmdb') or ''
        moviename = movie.get('originaltitle') or movie.get('title') or ''
        movieyear = movie.get('year')

        if not moviename:
            return False

        if tmdbid or imdbid:
            url = self.service[1] + '/movies/movie'
            if tmdbid:
                urldata = '?key=' + self.service[2] + '&tmdb_id=' + str(tmdbid)
            else:
                urldata = '?key=' + self.service[2] + '&imdb_id=' + str(imdbid)

            try:
                data = json.loads(get_urldata(url + urldata, '', "GET"))
                movie_bs_id = data['movie']['id']
                movie_tmdb_id = data['movie'].get('tmdb_id', 0) or 0
                return [int(movie_bs_id), int(movie_tmdb_id), int(playcount), bool(playstatus), '', moviename, 'movie']
            except:
                log("direct movie lookup failed, fallback to search: %s" % moviename, xbmc.LOGINFO)

        url = self.service[1] + '/movies/search'
        urldata = '?key=' + self.service[2] + '&title=' + urllib.parse.quote(moviename)
        try:
            data = json.loads(get_urldata(url + urldata, '', "GET"))
            best = self._pick_best_movie(data.get('movies', []), moviename, self._safe_int_year(movieyear))
            if not best:
                log("no BetaSeries movie match for '%s' (%s)" % (moviename, movieyear), xbmc.LOGINFO)
                return False

            movie_bs_id = best.get('id')
            movie_tmdb_id = best.get('tmdb_id') or 0
            return [int(movie_bs_id), int(movie_tmdb_id), int(playcount), bool(playstatus), '', moviename, 'movie']
        except:
            log("could not fetch movie BetaSeries id : %s" % moviename, xbmc.LOGINFO)
            return False

class MyMonitor(xbmc.Monitor):
    def __init__(self, *args, **kwargs):
        xbmc.Monitor.__init__(self)
        self.action = kwargs['action']

    def onSettingsChanged(self):
        log('onSettingsChanged')
        self.action()

if (__name__ == "__main__"):
    log('script version %s started' % __addonversion__)
    __useragent__ = set_user_agent()
    Main()