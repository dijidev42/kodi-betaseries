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
#  along with XBMC; see the file COPYING. If not, write to the
#  Free Software Foundation, 675 Mass Ave, Cambridge, MA 02139, USA.
#
#  code structure and portions of code based on service.scrobbler.librefm by Team-XBMC

import urllib.request
import urllib.parse
import urllib.error
import socket
import hashlib
import time
import platform

import xbmc
import xbmcaddon
import simplejson as json

__addon__ = xbmcaddon.Addon()
__addonid__ = __addon__.getAddonInfo('id')
__addonname__ = __addon__.getAddonInfo('name')
__addonversion__ = __addon__.getAddonInfo('version')
__icon__ = __addon__.getAddonInfo('icon')
__platform__ = platform.system() + " " + platform.release()
__language__ = __addon__.getLocalizedString

socket.setdefaulttimeout(10)

_notification_batch = {}
_notification_batch_last_ts = 0
_mass_update_started = False
_mass_update_started_ts = 0


def log(txt, loglevel=xbmc.LOGDEBUG):
    message = '%s: %s' % (__addonid__, txt)
    xbmc.log(msg=message, level=loglevel)


def notify(message_id_or_text, display_time=750):
    message = __language__(message_id_or_text) if isinstance(message_id_or_text, int) else message_id_or_text
    xbmc.executebuiltin('Notification(%s,%s,%s,%s)' % (__addonname__, message, display_time, __icon__))


def queue_batched_notification(media_type, action):
    global _notification_batch, _notification_batch_last_ts

    key = "%s_%s" % (media_type, action)
    _notification_batch[key] = _notification_batch.get(key, 0) + 1
    _notification_batch_last_ts = time.time()


def start_mass_update_notification():
    global _mass_update_started, _mass_update_started_ts

    now = time.time()

    if _mass_update_started and (now - _mass_update_started_ts) < 10:
        return

    _mass_update_started = True
    _mass_update_started_ts = now
    notify("Mise à jour BetaSeries en cours...", 1200)


def _flush_batched_notifications(force=False):
    global _notification_batch, _notification_batch_last_ts
    global _mass_update_started, _mass_update_started_ts

    if not _notification_batch:
        return

    now = time.time()
    if not force and (now - _notification_batch_last_ts) < 1.5:
        return

    ordered_keys = [
        'episode_watched',
        'episode_unwatched',
        'episode_downloaded',
        'movie_watched',
        'movie_unwatched',
    ]

    for key in ordered_keys:
        count = _notification_batch.get(key, 0)
        if not count:
            continue

        if key == 'episode_watched':
            msg = "%d épisode%s marqué%s comme vu%s" % (
                count,
                "s" if count > 1 else "",
                "s" if count > 1 else "",
                "s" if count > 1 else ""
            )
        elif key == 'episode_unwatched':
            msg = "%d épisode%s marqué%s comme non vu%s" % (
                count,
                "s" if count > 1 else "",
                "s" if count > 1 else "",
                "s" if count > 1 else ""
            )
        elif key == 'episode_downloaded':
            msg = "%d épisode%s marqué%s comme téléchargé%s" % (
                count,
                "s" if count > 1 else "",
                "s" if count > 1 else "",
                "s" if count > 1 else ""
            )
        elif key == 'movie_watched':
            msg = "%d film%s marqué%s comme vu%s" % (
                count,
                "s" if count > 1 else "",
                "s" if count > 1 else "",
                "s" if count > 1 else ""
            )
        elif key == 'movie_unwatched':
            msg = "%d film%s marqué%s comme non vu%s" % (
                count,
                "s" if count > 1 else "",
                "s" if count > 1 else "",
                "s" if count > 1 else ""
            )
        else:
            continue

        notify(msg, 1200)

    _notification_batch = {}
    _notification_batch_last_ts = 0
    _mass_update_started = False
    _mass_update_started_ts = 0


def set_user_agent():
    try:
        json_query = json.loads(xbmc.executeJSONRPC(
            '{ "jsonrpc": "2.0", "method": "Application.GetProperties", "params": {"properties": ["version", "name"]}, "id": 1 }'
        ))
        major = str(json_query['result']['version']['major'])
        minor = str(json_query['result']['version']['minor'])
        name = "Kodi" if int(major) >= 14 else "XBMC"
        version = "%s %s.%s" % (name, major, minor)
    except Exception:
        log("could not get app version")
        version = "XBMC"

    return "Mozilla/5.0 (compatible; %s; %s; %s/%s)" % (
        __platform__, version, __addonid__, __addonversion__
    )


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

    if getattr(connection, 'code', None):
        return connection.read()

    log('response empty')
    return 0


def get_json(url, urldata='', method='GET'):
    response = get_urldata(url, urldata, method)
    return json.loads(response)


def kodi_jsonrpc(method, params=None):
    payload = {
        "jsonrpc": "2.0",
        "method": method,
        "params": params or {},
        "id": 1
    }
    return json.loads(xbmc.executeJSONRPC(json.dumps(payload)))


class Main:
    def __init__(self):
        self._service_setup()
        monitor = xbmc.Monitor()
        while not monitor.abortRequested():
            _flush_batched_notifications(force=False)
            if monitor.waitForAbort(1):
                break

        _flush_batched_notifications(force=True)

    def _service_setup(self):
        self.apikey = 'cca540f2c2c4'
        self.apiurl = 'https://api.betaseries.com'
        self.apiver = '2.2'
        self.Monitor = MyMonitor(action=self._get_settings)
        self._get_settings()

    def _build_service(self):
        beta_active = __addon__.getSetting('betaactive') == 'true'
        beta_first = __addon__.getSetting('betafirst') == 'true'
        beta_user = __addon__.getSetting('betauser')
        beta_pass = __addon__.getSetting('betapass').encode('utf-8')
        beta_bulk = __addon__.getSetting('betabulk') == 'true'
        beta_mark = __addon__.getSetting('betamark') == 'true'
        beta_unmark = __addon__.getSetting('betaunmark') == 'true'
        beta_follow = __addon__.getSetting('betafollow') == 'true'
        beta_notify = __addon__.getSetting('betanotify') == 'true'

        if not (beta_active and beta_user and beta_pass):
            return []

        return [
            'betaseries', self.apiurl, self.apikey, beta_user, beta_pass,
            beta_first, '', False, 0, 0, 0,
            beta_bulk, beta_mark, beta_unmark, beta_follow, beta_notify
        ]

    def _get_settings(self):
        log('reading settings')
        service = self._build_service()

        if service:
            self.Player = MyPlayer(action=self._service_betaserie, service=service)
            if service[15]:
                notify(30003)

    def _service_betaserie(self, episode, service):
        tstamp = int(time.time())

        if service[7]:
            return

        if not service[6]:
            service = self._service_authenticate(service, tstamp)

        if service[6] and episode[0] and episode[1]:
            if not service[5] or (service[5] and episode[2] <= 1):
                self._service_mark(service, episode)

    def _service_authenticate(self, service, timestamp):
        if service[10] > int(timestamp):
            return service

        md5pass = hashlib.md5()
        md5pass.update(service[4])

        url = service[1] + '/members/auth'
        urldata = {
            'v': self.apiver,
            'key': service[2],
            'login': service[3],
            'password': md5pass.hexdigest()
        }

        try:
            data = get_json(url, urldata, "POST")
            log('successfully authenticated')
        except Exception:
            service = self._service_fail(service, True)
            notify(32003)
            log('failed to connect for authentication', xbmc.LOGINFO)
            return service

        if 'token' in data:
            service[6] = str(data['token'])
            service[8] = 0
            service[9] = 0
            service[10] = 0

        errors = data.get('errors')
        if errors:
            error = errors[0]
            code = error['code']
            text = error['text']
            log("%s error %s : %s" % (service[0], code, text), xbmc.LOGINFO)

            if code < 2000:
                notify(32002)
                log('bad API usage', xbmc.LOGINFO)
                __addon__.setSetting('betaactive', 'false')
            elif code > 4001:
                notify(32004)
                log('login or password incorrect', xbmc.LOGINFO)
                service[7] = True
            else:
                service = self._service_fail(service, True)
                notify(32001)
                log('server error while authenticating', xbmc.LOGINFO)

        return service

    def _follow_show_if_needed(self, service, episode):
        if episode[6] != 'episode' or not service[14] or episode[2] == -1:
            return service, True

        url = service[1] + "/shows/show"
        urldata = {
            'v': self.apiver,
            'key': service[2],
            'token': service[6],
            'thetvdb_id': episode[0]
        }

        try:
            data = get_json(url, urldata, "POST")
        except Exception:
            service = self._service_fail(service, False)
            log('failed to follow show %s' % episode[4], xbmc.LOGINFO)
            return service, False

        errors = data.get('errors')
        if not errors:
            if service[15]:
                notify(__language__(30013) + episode[4])
            log('now following show %s' % episode[4])
            return service, True

        error = errors[0]
        code = error['code']
        text = error['text']
        log("%s error : %s %s" % (service[0], code, text), xbmc.LOGINFO)

        if code == 2001:
            service[6] = ''
            log('bad token while following show', xbmc.LOGINFO)
            return service, False
        if code == 2003:
            log('already following show %s' % episode[4])
            return service, True

        notify(__language__(32005) + episode[4])
        log('failed to follow show %s' % episode[4], xbmc.LOGINFO)
        return service, False

    def _build_mark_request(self, service, episode):
        if episode[6] == 'movie':
            url = service[1] + "/movies/movie"
            urldata = {
                'v': self.apiver,
                'key': service[2],
                'token': service[6],
                'id': episode[0],
                'state': episode[2]
            }
            method = "POST"
            if episode[2] == 0:
                act = "not watched"
                actlang = 30017
            else:
                act = "watched"
                actlang = 30016
            return url, urldata, method, act, actlang

        urldata = {
            'v': self.apiver,
            'key': service[2],
            'token': service[6],
            'thetvdb_id': episode[1]
        }

        if service[11]:
            urldata['bulk'] = 1

        if episode[2] == 0:
            return service[1] + "/episodes/watched", urldata, "DELETE", "not watched", 30015
        if episode[2] == -1:
            return service[1] + "/episodes/downloaded", urldata, "POST", "downloaded", 30101
        return service[1] + "/episodes/watched", urldata, "POST", "watched", 30014

    def _queue_success_notification(self, service, episode):
        if not service[15]:
            return

        total_before = sum(_notification_batch.values())
        if total_before == 0:
            start_mass_update_notification()

        if episode[6] == 'movie':
            if episode[2] == 0:
                queue_batched_notification('movie', 'unwatched')
            else:
                queue_batched_notification('movie', 'watched')
        else:
            if episode[2] == 0:
                queue_batched_notification('episode', 'unwatched')
            elif episode[2] == -1:
                queue_batched_notification('episode', 'downloaded')
            else:
                queue_batched_notification('episode', 'watched')

    def _service_mark(self, service, episode):
        log('marking item: %s' % episode)

        if not service[12] and episode[2] > 0 and not episode[3]:
            log("abort marking, as play = %s" % episode[3])
            return service

        if not service[13] and episode[2] == 0 and not episode[3]:
            log("abort unmarking, as play = %s" % episode[3])
            return service

        service, ok = self._follow_show_if_needed(service, episode)
        if not ok:
            return service

        url, urldata, method, act, actlang = self._build_mark_request(service, episode)

        try:
            data = get_json(url, urldata, method)
        except Exception:
            service = self._service_fail(service, False)
            log('failed to mark as %s' % act, xbmc.LOGINFO)
            return service

        errors = data.get('errors')
        if errors:
            error = errors[0]
            code = error['code']
            text = error['text']
            log("%s error : %s %s" % (service[0], code, text), xbmc.LOGINFO)

            if code == 2001:
                service[6] = ''
                log('bad token while marking %s' % episode[6], xbmc.LOGINFO)
            elif code == 0:
                if episode[6] == 'movie':
                    log('%s already marked as %s' % (episode[5], act), xbmc.LOGINFO)
                else:
                    log('not following show, or %s %s already marked as %s' % (episode[6], episode[5], act), xbmc.LOGINFO)
            else:
                notify(32007 if episode[6] == 'movie' else 32006)
                log('error marking %s %s as %s' % (episode[6], episode[5], act), xbmc.LOGINFO)
        else:
            self._queue_success_notification(service, episode)
            _flush_batched_notifications(force=False)
            log('%s %s %s marked as %s' % (episode[4], episode[6], episode[5], act))

        return service

    def _service_fail(self, service, timer):
        timestamp = int(time.time())
        service[8] += 1

        if service[8] > 2:
            service[6] = ''

        if timer:
            if service[9] in (0, 7680):
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
        except Exception:
            return None

    def _pick_best_match(self, items, wanted_title, year=None, title_keys=None, year_keys=None):
        if not items:
            return None, -9999

        title_keys = title_keys or []
        year_keys = year_keys or []

        wanted = self._norm(wanted_title)
        best = None
        best_score = -9999

        for item in items:
            score = 0

            for key in title_keys:
                candidate = self._norm(item.get(key))
                if not candidate:
                    continue
                if candidate == wanted:
                    score += 120
                elif wanted in candidate or candidate in wanted:
                    score += 40

            item_year = None
            for key in year_keys:
                item_year = self._safe_int_year(item.get(key))
                if item_year:
                    break

            if year and item_year:
                if item_year == year:
                    score += 80
                elif abs(item_year - year) == 1:
                    score += 25

            if score > best_score:
                best_score = score
                best = item

        return best, best_score

    def _pick_best_show(self, shows, showtitle, year=None):
        best, best_score = self._pick_best_match(
            shows,
            showtitle,
            year=year,
            title_keys=['title', 'original_title', 'slug'],
            year_keys=['creation', 'release_date', 'year']
        )
        log("best show match for '%s' (%s): %s score=%s" % (
            showtitle,
            year,
            best.get('title') if best else 'None',
            best_score
        ))
        return best

    def _pick_best_movie(self, movies, movietitle, year=None):
        best, best_score = self._pick_best_match(
            movies,
            movietitle,
            year=year,
            title_keys=['title', 'original_title'],
            year_keys=['production_year', 'release_date', 'year']
        )
        log("best movie match for '%s' (%s): %s score=%s" % (
            movietitle,
            year,
            best.get('title') if best else 'None',
            best_score
        ))
        return best

    def _get_result_item(self, data):
        try:
            result = json.loads(data)
            return result.get('item', {}), result
        except Exception:
            return {}, {}

    def onNotification(self, sender, method, data):
        if sender != 'xbmc':
            return

        if method == 'VideoLibrary.OnScanFinished':
            self.ScanRecentlyadded()
            _flush_batched_notifications(force=True)
            return

        if method == 'Player.OnPlay':
            item, _ = self._get_result_item(data)
            if 'id' in item and item.get('type') in ('episode', 'movie'):
                xbmc.sleep(1000)
                log("watching %s, library id = %s" % (item['type'], item['id']))
                self.Play = True
            return

        if method == 'Player.OnStop':
            item, result = self._get_result_item(data)
            if 'title' in item and 'id' in item and result.get("end"):
                if item.get('type') == 'episode':
                    try:
                        scraper_url = "%s/episodes/scraper?file=%s&key=%s" % (
                            self.service[1], item["title"], self.service[2]
                        )
                        scraper_data = get_json(scraper_url, "", "GET")["episode"]
                        title = str(scraper_data["season"]) + "x" + str(scraper_data["episode"])

                        show_url = "%s/shows/display?id=%s&key=%s" % (
                            self.service[1], scraper_data["show_id"], self.service[2]
                        )
                        tvdbid = get_json(show_url, "", "GET")["show"]["thetvdb_id"]
                        episode = [
                            int(tvdbid),
                            int(scraper_data["thetvdb_id"]),
                            1,
                            True,
                            str(scraper_data["show_title"]),
                            title,
                            'episode'
                        ]
                        self.action(episode, self.service)
                    except Exception:
                        log("failed to resolve episode from scraper endpoint", xbmc.LOGINFO)

                elif item.get('type') == 'movie':
                    try:
                        scraper_url = "%s/movies/scraper?file=%s&key=%s" % (
                            self.service[1], item["title"], self.service[2]
                        )
                        scraper_data = get_json(scraper_url, "", "GET")["movie"]
                        movie = [
                            int(scraper_data["id"]),
                            int(scraper_data.get("thetvdb_id", 0) or 0),
                            1,
                            True,
                            '',
                            str(scraper_data["title"]),
                            'movie'
                        ]
                        self.action(movie, self.service)
                    except Exception:
                        log("failed to resolve movie from scraper endpoint", xbmc.LOGINFO)
            else:
                xbmc.sleep(1000)

            self.Play = False
            _flush_batched_notifications(force=True)
            return

        if method == 'VideoLibrary.OnUpdate':
            try:
                result = json.loads(data)
            except Exception:
                return

            if 'playcount' not in result or 'item' not in result:
                return

            item = result['item']
            playcount = result['playcount']

            if item.get('type') == 'episode':
                log("episode status changed for library id = %s, playcount = %s" % (item['id'], playcount))
                episode = self._get_episode_info(item['id'], playcount, self.Play)
                if episode:
                    self.action(episode, self.service)
                    self.Play = False
                    if playcount == 0:
                        episode[2] = -1
                        self.action(episode, self.service)

            elif item.get('type') == 'movie':
                log("movie status changed for library id = %s, playcount = %s" % (item['id'], playcount))
                movie = self._get_movie_info(item['id'], playcount, self.Play)
                if movie:
                    self.action(movie, self.service)
                    self.Play = False

            _flush_batched_notifications(force=False)

    def ScanRecentlyadded(self):
        filepath = __addon__.getAddonInfo('path') + '/lastdate.tmp'

        try:
            with open(filepath, "r") as fic:
                lastdate = fic.read()
        except Exception:
            lastdate = '2001-01-01 00:00:00'

        newdate = lastdate
        result_episodes = kodi_jsonrpc(
            "VideoLibrary.GetRecentlyAddedEpisodes",
            {"properties": ["dateadded"]}
        )

        if 'result' not in result_episodes:
            log("VideoLibrary GetRecentlyAddedEpisodes ERROR : %s" % result_episodes)
            return

        for episode in result_episodes['result'].get('episodes', []):
            if episode['dateadded'] > lastdate:
                if episode['dateadded'] > newdate:
                    newdate = episode['dateadded']

                log("%s with id %s has been added %s" % (
                    episode['label'], episode['episodeid'], episode['dateadded']
                ))

                ep_info = self._get_episode_info(episode['episodeid'], -1, self.Play)
                if ep_info and isinstance(ep_info, list):
                    ep_info[2] = -1
                    self.action(ep_info, self.service)

        with open(filepath, 'wb') as fic:
            fic.write(newdate.encode('utf-8'))

        _flush_batched_notifications(force=True)

    def _get_episode_details(self, episodeid):
        return kodi_jsonrpc(
            "VideoLibrary.GetEpisodeDetails",
            {"episodeid": episodeid, "properties": ["tvshowid", "showtitle", "season", "episode", "uniqueid"]}
        )['result']['episodedetails']

    def _get_tvshow_details(self, tvshowid):
        return kodi_jsonrpc(
            "VideoLibrary.GetTVShowDetails",
            {"tvshowid": tvshowid, "properties": ["year", "title", "originaltitle", "uniqueid"]}
        )['result']['tvshowdetails']

    def _get_movie_details(self, movieid):
        return kodi_jsonrpc(
            "VideoLibrary.GetMovieDetails",
            {"movieid": movieid, "properties": ["title", "originaltitle", "imdbnumber", "uniqueid", "year"]}
        )['result']['moviedetails']

    def _search_show_tvdbid(self, showtitle, show_year):
        url = self.service[1] + '/shows/search'
        query = '?v=2.2&key=%s&title=%s' % (self.service[2], urllib.parse.quote(showtitle))
        data = get_json(url + query, '', "GET")
        best = self._pick_best_show(data.get('shows', []), showtitle, self._safe_int_year(show_year))
        if best:
            return best.get('thetvdb_id')
        return ''

    def _search_episode_tvdbid(self, tvdbid, season, episode_num):
        url = self.service[1] + '/shows/episodes'
        query = '?v=2.2&key=%s&thetvdb_id=%s&season=%s&episode=%s' % (
            self.service[2], str(tvdbid), str(season), str(episode_num)
        )
        data = get_json(url + query, '', "GET")
        episodes = data.get('episodes', [])
        if episodes:
            return episodes[0].get('thetvdb_id')
        return ''

    def _get_episode_info(self, episodeid, playcount, playstatus):
        showtitle = ''
        season = None
        episode_num = None
        show_year = None
        tvdbid = ''
        tvdbepid = ''

        try:
            ep = self._get_episode_details(episodeid)
            showtitle = ep.get('showtitle', '')
            season = ep.get('season')
            episode_num = ep.get('episode')
            tvshowid = ep.get('tvshowid')

            if tvshowid is not None:
                show = self._get_tvshow_details(tvshowid)
                show_year = show.get('year')
                show_uniqueid = show.get('uniqueid', {}) or {}
                tvdbid = show_uniqueid.get('tvdb') or show_uniqueid.get('thetvdb') or ''
                if not showtitle:
                    showtitle = show.get('title') or show.get('originaltitle') or ''
        except Exception:
            log("could not get episode details", xbmc.LOGINFO)
            return False

        if not showtitle or season is None or episode_num is None:
            return False

        if not tvdbid:
            try:
                tvdbid = self._search_show_tvdbid(showtitle, show_year)
            except Exception:
                log("could not fetch tvshow's thetvdb_id", xbmc.LOGINFO)
                return False

        if not tvdbid:
            log("could not fetch tvshow's thetvdb_id", xbmc.LOGINFO)
            return False

        try:
            tvdbepid = self._search_episode_tvdbid(tvdbid, season, episode_num)
        except Exception:
            log("could not fetch episode's thetvdb_id", xbmc.LOGINFO)
            return False

        if not tvdbepid:
            log("could not fetch episode's thetvdb_id for %s S%02dE%02d" % (
                showtitle, season, episode_num
            ), xbmc.LOGINFO)
            return False

        epname = str(season) + 'x' + str(episode_num)
        return [int(tvdbid), int(tvdbepid), int(playcount), bool(playstatus), showtitle, epname, 'episode']

    def _lookup_movie_by_ids(self, tmdbid, imdbid):
        url = self.service[1] + '/movies/movie'
        if tmdbid:
            query = '?key=%s&tmdb_id=%s' % (self.service[2], str(tmdbid))
        else:
            query = '?key=%s&imdb_id=%s' % (self.service[2], str(imdbid))

        data = get_json(url + query, '', "GET")
        movie_bs_id = data['movie']['id']
        movie_tmdb_id = data['movie'].get('tmdb_id', 0) or 0
        return int(movie_bs_id), int(movie_tmdb_id)

    def _search_movie_ids(self, moviename, movieyear):
        url = self.service[1] + '/movies/search'
        query = '?key=%s&title=%s' % (self.service[2], urllib.parse.quote(moviename))
        data = get_json(url + query, '', "GET")
        best = self._pick_best_movie(data.get('movies', []), moviename, self._safe_int_year(movieyear))
        if not best:
            return None, None
        return best.get('id'), (best.get('tmdb_id') or 0)

    def _get_movie_info(self, movieid, playcount, playstatus):
        try:
            movie = self._get_movie_details(movieid)
        except Exception:
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
            try:
                movie_bs_id, movie_tmdb_id = self._lookup_movie_by_ids(tmdbid, imdbid)
                return [int(movie_bs_id), int(movie_tmdb_id), int(playcount), bool(playstatus), '', moviename, 'movie']
            except Exception:
                log("direct movie lookup failed, fallback to search: %s" % moviename, xbmc.LOGINFO)

        try:
            movie_bs_id, movie_tmdb_id = self._search_movie_ids(moviename, movieyear)
            if not movie_bs_id:
                log("no BetaSeries movie match for '%s' (%s)" % (moviename, movieyear), xbmc.LOGINFO)
                return False

            return [int(movie_bs_id), int(movie_tmdb_id or 0), int(playcount), bool(playstatus), '', moviename, 'movie']
        except Exception:
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