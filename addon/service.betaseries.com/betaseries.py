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

import os
import sys
import urllib.request
import urllib.parse
import urllib.error
import socket
import hashlib
import time
import platform

import xbmc
import xbmcaddon
import xbmcvfs
import xbmcgui
import simplejson as json

__addon__ = xbmcaddon.Addon()
__addonid__ = __addon__.getAddonInfo('id')
__addonname__ = __addon__.getAddonInfo('name')
__addonversion__ = __addon__.getAddonInfo('version')
__icon__ = __addon__.getAddonInfo('icon')
__platform__ = platform.system() + " " + platform.release()
__language__ = __addon__.getLocalizedString
__addonpath__ = xbmcvfs.translatePath(__addon__.getAddonInfo('path'))
__profile__ = xbmcvfs.translatePath(__addon__.getAddonInfo('profile'))

socket.setdefaulttimeout(10)

_notification_batch = {}
_notification_batch_last_ts = 0
_mass_update_started = False
_mass_update_started_ts = 0

EPISODES_INDEX_FILE = os.path.join(__profile__, 'episodes_sync_index.json')
MOVIES_INDEX_FILE = os.path.join(__profile__, 'movies_sync_index.json')
STOP_EPISODES_FILE = os.path.join(__profile__, 'sync_episodes.stop')
STOP_MOVIES_FILE = os.path.join(__profile__, 'sync_movies.stop')


def ensure_profile_dir():
    try:
        if not os.path.isdir(__profile__):
            os.makedirs(__profile__)
    except Exception:
        log('could not create profile dir', xbmc.LOGINFO)


def log(txt, loglevel=xbmc.LOGDEBUG):
    message = '%s: %s' % (__addonid__, txt)
    xbmc.log(msg=message, level=loglevel)


def notify(message_id_or_text, display_time=1000):
    message = __language__(message_id_or_text) if isinstance(message_id_or_text, int) else message_id_or_text
    xbmc.executebuiltin('Notification(%s,%s,%s,%s)' % (__addonname__, message, display_time, __icon__))


def format_item_label(item):
    if item[6] == 'episode':
        return '%s - %s' % (item[4], item[5])
    return item[5]


def extract_api_error(data):
    try:
        errors = data.get('errors')
        if errors and len(errors) > 0:
            code = errors[0].get('code', 'n/a')
            text = errors[0].get('text', 'unknown error')
            return code, text
    except Exception:
        pass
    return None, None


def log_api_error(item, context, data):
    code, text = extract_api_error(data)
    if code is not None:
        log('%s failed for %s - API error %s: %s' % (
            context, format_item_label(item), str(code), str(text)
        ), xbmc.LOGERROR)
    else:
        log('%s failed for %s - unknown API error: %s' % (
            context, format_item_label(item), repr(data)
        ), xbmc.LOGERROR)


def queue_batched_notification(media_type, action):
    global _notification_batch, _notification_batch_last_ts
    key = '%s_%s' % (media_type, action)
    _notification_batch[key] = _notification_batch.get(key, 0) + 1
    _notification_batch_last_ts = time.time()


def start_mass_update_notification(prefix=None):
    global _mass_update_started, _mass_update_started_ts
    now = time.time()
    if _mass_update_started and (now - _mass_update_started_ts) < 10:
        return
    _mass_update_started = True
    _mass_update_started_ts = now
    notify(prefix or 30200, 1500)


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
            msg = __language__(30218) % count
        elif key == 'episode_unwatched':
            msg = __language__(30219) % count
        elif key == 'episode_downloaded':
            msg = __language__(30220) % count
        elif key == 'movie_watched':
            msg = __language__(30221) % count
        elif key == 'movie_unwatched':
            msg = __language__(30222) % count
        else:
            continue

        notify(msg, 1500)

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
        name = 'Kodi' if int(major) >= 14 else 'XBMC'
        version = '%s %s.%s' % (name, major, minor)
    except Exception:
        log('could not get app version')
        version = 'XBMC'

    return 'Mozilla/5.0 (compatible; %s; %s; %s/%s)' % (__platform__, version, __addonid__, __addonversion__)


def get_urldata(url, urldata, method):
    handler = urllib.request.HTTPSHandler()
    opener = urllib.request.build_opener(handler)
    body = None if urldata == '' else urllib.parse.urlencode(urldata).encode('utf-8')

    req = urllib.request.Request(url, data=body)
    req.add_header('Accept', 'application/json')
    req.add_header('User-Agent', __useragent__)
    req.get_method = lambda: method

    try:
        connection = opener.open(req)
        return connection.read()

    except urllib.error.HTTPError as e:
        response_body = b''
        response_text = ''

        try:
            response_body = e.read()
            response_text = response_body.decode('utf-8', 'replace')
        except Exception:
            response_body = b''
            response_text = ''

        silent_error = False
        try:
            data = json.loads(response_text)
            errors = data.get('errors', [])
            if errors and errors[0].get('code') == 2003:
                silent_error = True
        except Exception:
            pass

        if not silent_error:
            log('HTTP error %s for %s: %s' % (
                str(getattr(e, 'code', 'n/a')),
                url,
                str(getattr(e, 'reason', 'n/a'))
            ), xbmc.LOGERROR)

        return response_body

    except Exception as e:
        log('request error for %s: %s' % (url, repr(e)), xbmc.LOGERROR)
        raise


def get_json(url, urldata='', method='GET'):
    response = get_urldata(url, urldata, method)
    return json.loads(response)


def kodi_jsonrpc(method, params=None):
    payload = {
        'jsonrpc': '2.0',
        'method': method,
        'params': params or {},
        'id': 1
    }
    return json.loads(xbmc.executeJSONRPC(json.dumps(payload)))


def parse_params(argv):
    if len(argv) < 2 or not argv[1]:
        return {}
    raw = argv[1]
    if raw.startswith('?'):
        raw = raw[1:]
    parsed = urllib.parse.parse_qs(raw)
    return dict((k, v[0]) for k, v in parsed.items())


def load_index(filepath):
    ensure_profile_dir()
    try:
        with open(filepath, 'r') as f:
            data = json.loads(f.read())
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {}


def save_index(filepath, data):
    ensure_profile_dir()
    with open(filepath, 'w') as f:
        f.write(json.dumps(data))


def create_stop_flag(filepath):
    ensure_profile_dir()
    try:
        with open(filepath, 'w') as f:
            f.write('1')
    except Exception:
        pass


def clear_stop_flag(filepath):
    try:
        if os.path.exists(filepath):
            os.remove(filepath)
    except Exception:
        pass


def stop_requested(filepath, monitor=None):
    if monitor and monitor.abortRequested():
        return True
    return os.path.exists(filepath)


def safe_label(text, max_len=70):
    if text is None:
        return ''
    text = str(text).replace('\n', ' ').replace('\r', ' ').strip()
    if len(text) <= max_len:
        return text
    return text[:max_len - 3] + '...'


class SyncProgressDialog:
    def __init__(self, heading):
        self.heading = heading
        self.dialog = xbmcgui.DialogProgress()
        self.created = False

    def _message(self, line1='', line2='', line3=''):
        parts = [x for x in [line1, line2, line3] if x]
        return '\n'.join(parts)

    def create(self, line1=None, line2='', line3=''):
        self.dialog.create(self.heading, self._message(line1 or __language__(30203), line2, line3))
        self.created = True

    def update(self, current, total, line1='', line2='', line3=''):
        if not self.created:
            self.create(line1, line2, line3)
        percent = 0
        if total > 0:
            percent = int((float(current) / float(total)) * 100)
        if percent < 0:
            percent = 0
        if percent > 100:
            percent = 100
        self.dialog.update(percent, self._message(line1, line2, line3))

    def iscanceled(self):
        try:
            return self.dialog.iscanceled()
        except Exception:
            return False

    def close(self):
        try:
            if self.created:
                self.dialog.close()
        except Exception:
            pass


class BetaSeriesAgent:
    def __init__(self):
        self.apikey = 'cca540f2c2c4'
        self.apiurl = 'https://api.betaseries.com'
        self.apiver = '2.2'
        self.service = self._build_service()

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

    def is_ready(self):
        return bool(self.service)

    def authenticate_if_needed(self):
        tstamp = int(time.time())
        service = self.service
        if service[7]:
            return False
        if service[6]:
            return True
        self.service = self._service_authenticate(service, tstamp)
        return bool(self.service[6])

    def _service_authenticate(self, service, timestamp):
        if service[10] > int(timestamp):
            return service

        md5pass = hashlib.md5()
        md5pass.update(service[4])
        url = service[1] + '/members/auth'
        urldata = {'v': self.apiver, 'key': service[2], 'login': service[3], 'password': md5pass.hexdigest()}

        try:
            data = get_json(url, urldata, 'POST')
            log('successfully authenticated')
        except Exception:
            service = self._service_fail(service, True)
            notify(32003)
            log('failed to connect for authentication', xbmc.LOGERROR)
            return service

        if 'token' in data:
            service[6] = str(data['token'])
            service[8] = 0
            service[9] = 0
            service[10] = 0

        errors = data.get('errors')
        if errors:
            code = errors[0]['code']
            text = errors[0]['text']
            log('authentication failed - API error %s: %s' % (str(code), str(text)), xbmc.LOGERROR)
            if code < 2000:
                notify(32002)
                __addon__.setSetting('betaactive', 'false')
            elif code > 4001:
                notify(32004)
                service[7] = True
            else:
                service = self._service_fail(service, True)
                notify(32001)
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

    def _follow_show_if_needed(self, episode):
        service = self.service
        if episode[6] != 'episode' or not service[14] or episode[2] == -1:
            return True

        url = service[1] + '/shows/show'
        urldata = {
            'v': self.apiver,
            'key': service[2],
            'token': service[6],
            'thetvdb_id': episode[0]
        }

        try:
            data = get_json(url, urldata, 'POST')
        except Exception:
            self.service = self._service_fail(service, False)
            log('follow show failed for %s' % format_item_label(episode), xbmc.LOGERROR)
            return False

        errors = data.get('errors')
        if not errors:
            if service[15]:
                notify(__language__(30013) + episode[4])
            return True

        code = errors[0]['code']

        if code == 2001:
            service[6] = ''
            return False

        if code == 2003:
            return True

        log_api_error(episode, 'Follow show', data)
        notify(__language__(32005) + episode[4])
        return False

    def _build_mark_request(self, item):
        service = self.service
        if item[6] == 'movie':
            url = service[1] + '/movies/movie'
            urldata = {'v': self.apiver, 'key': service[2], 'token': service[6], 'id': item[0], 'state': item[2]}
            method = 'POST'
            act = 'not watched' if item[2] == 0 else 'watched'
            return url, urldata, method, act

        urldata = {'v': self.apiver, 'key': service[2], 'token': service[6], 'thetvdb_id': item[1]}
        if service[11]:
            urldata['bulk'] = 1
        if item[2] == 0:
            return service[1] + '/episodes/watched', urldata, 'DELETE', 'not watched'
        if item[2] == -1:
            return service[1] + '/episodes/downloaded', urldata, 'POST', 'downloaded'
        return service[1] + '/episodes/watched', urldata, 'POST', 'watched'

    def _queue_success_notification(self, item):
        if not self.service[15]:
            return
        total_before = sum(_notification_batch.values())
        if total_before == 0:
            start_mass_update_notification()
        if item[6] == 'movie':
            queue_batched_notification('movie', 'unwatched' if item[2] == 0 else 'watched')
        else:
            if item[2] == 0:
                queue_batched_notification('episode', 'unwatched')
            elif item[2] == -1:
                queue_batched_notification('episode', 'downloaded')
            else:
                queue_batched_notification('episode', 'watched')

    def mark_item(self, item, force=True):
        service = self.service
        if not self.authenticate_if_needed():
            return False

        if not force:
            if not service[12] and item[2] > 0 and not item[3]:
                return False
            if not service[13] and item[2] == 0 and not item[3]:
                return False

        if item[6] == 'episode' and not self._follow_show_if_needed(item):
            return False

        url, urldata, method, act = self._build_mark_request(item)
        try:
            data = get_json(url, urldata, method)
        except Exception:
            self.service = self._service_fail(service, False)
            log('sync failed for %s' % format_item_label(item), xbmc.LOGERROR)
            return False

        errors = data.get('errors')
        if errors:
            log_api_error(item, 'Sync', data)
            code = errors[0]['code']
            if code == 2001:
                service[6] = ''
            elif code not in (0,):
                notify(__language__(30217) % format_item_label(item), 1200)
            return False

        self._queue_success_notification(item)
        _flush_batched_notifications(force=False)
        log('%s marked as %s' % (format_item_label(item), act))
        return True


class KodiLibraryResolver:
    def __init__(self, agent):
        self.agent = agent
        self.service = agent.service

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
            shows, showtitle, year,
            ['title', 'original_title', 'slug'],
            ['creation', 'release_date', 'year']
        )
        log("best show match for '%s' (%s): %s score=%s" % (
            showtitle, year, best.get('title') if best else 'None', best_score
        ))
        return best

    def _pick_best_movie(self, movies, movietitle, year=None):
        best, best_score = self._pick_best_match(
            movies, movietitle, year,
            ['title', 'original_title'],
            ['production_year', 'release_date', 'year']
        )
        log("best movie match for '%s' (%s): %s score=%s" % (
            movietitle, year, best.get('title') if best else 'None', best_score
        ))
        return best

    def _search_show_tvdbid(self, showtitle, show_year):
        url = self.service[1] + '/shows/search'
        query = '?v=2.2&key=%s&title=%s' % (self.service[2], urllib.parse.quote(showtitle))
        data = get_json(url + query, '', 'GET')
        best = self._pick_best_show(data.get('shows', []), showtitle, self._safe_int_year(show_year))
        if best:
            return best.get('thetvdb_id')
        return ''

    def _search_episode_tvdbid(self, tvdbid, season, episode_num):
        url = self.service[1] + '/shows/episodes'
        query = '?v=2.2&key=%s&thetvdb_id=%s&season=%s&episode=%s' % (
            self.service[2], str(tvdbid), str(season), str(episode_num)
        )
        data = get_json(url + query, '', 'GET')
        episodes = data.get('episodes', [])
        if episodes:
            return episodes[0].get('thetvdb_id')
        return ''

    def get_episode_info(self, episodeid, playcount, playstatus):
        showtitle = ''
        season = None
        episode_num = None
        show_year = None
        tvdbid = ''
        tvdbepid = ''

        try:
            ep = kodi_jsonrpc(
                'VideoLibrary.GetEpisodeDetails',
                {'episodeid': episodeid, 'properties': ['tvshowid', 'showtitle', 'season', 'episode', 'uniqueid']}
            )['result']['episodedetails']
            showtitle = ep.get('showtitle', '')
            season = ep.get('season')
            episode_num = ep.get('episode')
            tvshowid = ep.get('tvshowid')

            if tvshowid is not None:
                show = kodi_jsonrpc(
                    'VideoLibrary.GetTVShowDetails',
                    {'tvshowid': tvshowid, 'properties': ['year', 'title', 'originaltitle', 'uniqueid']}
                )['result']['tvshowdetails']
                show_year = show.get('year')
                show_uniqueid = show.get('uniqueid', {}) or {}
                tvdbid = show_uniqueid.get('tvdb') or show_uniqueid.get('thetvdb') or ''
                if not showtitle:
                    showtitle = show.get('title') or show.get('originaltitle') or ''
        except Exception:
            log('could not get episode details', xbmc.LOGERROR)
            return False

        if not showtitle or season is None or episode_num is None:
            return False

        if not tvdbid:
            try:
                tvdbid = self._search_show_tvdbid(showtitle, show_year)
            except Exception:
                log("could not fetch tvshow's thetvdb_id for %s" % showtitle, xbmc.LOGERROR)
                return False

        if not tvdbid:
            log("could not fetch tvshow's thetvdb_id for %s" % showtitle, xbmc.LOGERROR)
            return False

        try:
            tvdbepid = self._search_episode_tvdbid(tvdbid, season, episode_num)
        except Exception:
            log("could not fetch episode's thetvdb_id for %s S%02dE%02d" % (
                showtitle, int(season), int(episode_num)
            ), xbmc.LOGERROR)
            return False

        if not tvdbepid:
            log("resolve failed for %s - S%02dE%02d: episode not found on BetaSeries" % (
                showtitle, int(season), int(episode_num)
            ), xbmc.LOGERROR)
            return False

        epname = str(season) + 'x' + str(episode_num)
        return [int(tvdbid), int(tvdbepid), int(playcount), bool(playstatus), showtitle, epname, 'episode']

    def _lookup_movie_by_ids(self, tmdbid, imdbid):
        url = self.service[1] + '/movies/movie'
        if tmdbid:
            query = '?key=%s&tmdb_id=%s' % (self.service[2], str(tmdbid))
        else:
            query = '?key=%s&imdb_id=%s' % (self.service[2], str(imdbid))
        data = get_json(url + query, '', 'GET')
        movie_bs_id = data['movie']['id']
        movie_tmdb_id = data['movie'].get('tmdb_id', 0) or 0
        return int(movie_bs_id), int(movie_tmdb_id)

    def _search_movie_ids(self, moviename, movieyear):
        url = self.service[1] + '/movies/search'
        query = '?key=%s&title=%s' % (self.service[2], urllib.parse.quote(moviename))
        data = get_json(url + query, '', 'GET')
        best = self._pick_best_movie(data.get('movies', []), moviename, self._safe_int_year(movieyear))
        if not best:
            return None, None
        return best.get('id'), (best.get('tmdb_id') or 0)

    def get_movie_info(self, movieid, playcount, playstatus):
        try:
            movie = kodi_jsonrpc(
                'VideoLibrary.GetMovieDetails',
                {'movieid': movieid, 'properties': ['title', 'originaltitle', 'imdbnumber', 'uniqueid', 'year']}
            )['result']['moviedetails']
        except Exception:
            log("could not get movie details", xbmc.LOGERROR)
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
                log("direct movie lookup failed for %s, fallback to search" % moviename, xbmc.LOGERROR)

        try:
            movie_bs_id, movie_tmdb_id = self._search_movie_ids(moviename, movieyear)
            if not movie_bs_id:
                log("no BetaSeries movie match for '%s' (%s)" % (moviename, str(movieyear)), xbmc.LOGERROR)
                return False

            return [int(movie_bs_id), int(movie_tmdb_id or 0), int(playcount), bool(playstatus), '', moviename, 'movie']
        except Exception:
            log("could not fetch movie BetaSeries id : %s" % moviename, xbmc.LOGERROR)
            return False


class ManualSync:
    def __init__(self, agent, resolver):
        self.agent = agent
        self.resolver = resolver
        self.monitor = xbmc.Monitor()

    def _make_progress_lines(self, media_label, current, total, updated, skipped, current_label):
        percent = int((float(current) / float(total)) * 100) if total else 0
        line1 = '%s : %d / %d (%d%%)' % (media_label, current, total, percent)
        line2 = __language__(30207) % (updated, skipped)
        line3 = safe_label(current_label or __language__(30204))
        return line1, line2, line3

    def _should_stop(self, stop_file, progress_dialog):
        if stop_requested(stop_file, self.monitor):
            return True
        if progress_dialog and progress_dialog.iscanceled():
            create_stop_flag(stop_file)
            return True
        return False

    def sync_episodes(self, reset=False):
        clear_stop_flag(STOP_EPISODES_FILE)
        index = {} if reset else load_index(EPISODES_INDEX_FILE)
        data = kodi_jsonrpc('VideoLibrary.GetEpisodes', {'properties': ['playcount', 'showtitle', 'season', 'episode']})
        episodes = data.get('result', {}).get('episodes', [])
        total = len(episodes)
        start_mass_update_notification(__language__(30201))
        updated = 0
        skipped = 0
        new_index = dict(index)
        progress = SyncProgressDialog(__addonname__)
        progress.create(__language__(30201), __language__(30204), '0 / %d' % total)
        canceled = False

        try:
            for i, ep in enumerate(episodes, 1):
                current_label = '%s - S%02dE%02d' % (
                    ep.get('showtitle', __language__(30208)),
                    int(ep.get('season') or 0),
                    int(ep.get('episode') or 0)
                )
                line1, line2, line3 = self._make_progress_lines(__language__(30205), i, total, updated, skipped, current_label)
                progress.update(i, total, line1, line2, line3)

                if self._should_stop(STOP_EPISODES_FILE, progress):
                    canceled = True
                    notify(30210, 2000)
                    break

                episodeid = ep.get('episodeid')
                playcount = int(ep.get('playcount') or 0)
                item = self.resolver.get_episode_info(episodeid, playcount, False)
                if not item:
                    continue

                key = str(item[1])
                state = item[2]
                if key in index and index.get(key, {}).get('state') == state:
                    skipped += 1
                    continue

                if self.agent.mark_item(item, force=True):
                    updated += 1
                    new_index[key] = {
                        'state': state,
                        'ts': int(time.time()),
                        'label': item[5],
                        'show': item[4]
                    }
        finally:
            progress.close()
            save_index(EPISODES_INDEX_FILE, new_index)
            clear_stop_flag(STOP_EPISODES_FILE)
            _flush_batched_notifications(force=True)

        if not canceled:
            notify(__language__(30212) % (updated, skipped, total), 2500)

    def sync_movies(self, reset=False):
        clear_stop_flag(STOP_MOVIES_FILE)
        index = {} if reset else load_index(MOVIES_INDEX_FILE)
        data = kodi_jsonrpc('VideoLibrary.GetMovies', {'properties': ['playcount', 'title', 'originaltitle']})
        movies = data.get('result', {}).get('movies', [])
        total = len(movies)
        start_mass_update_notification(__language__(30202))
        updated = 0
        skipped = 0
        new_index = dict(index)
        progress = SyncProgressDialog(__addonname__)
        progress.create(__language__(30202), __language__(30204), '0 / %d' % total)
        canceled = False

        try:
            for i, mv in enumerate(movies, 1):
                current_label = mv.get('originaltitle') or mv.get('title') or __language__(30209)
                line1, line2, line3 = self._make_progress_lines(__language__(30206), i, total, updated, skipped, current_label)
                progress.update(i, total, line1, line2, line3)

                if self._should_stop(STOP_MOVIES_FILE, progress):
                    canceled = True
                    notify(30211, 2000)
                    break

                movieid = mv.get('movieid')
                playcount = int(mv.get('playcount') or 0)
                item = self.resolver.get_movie_info(movieid, playcount, False)
                if not item:
                    continue

                key = 'movie_%s' % item[0]
                state = item[2]
                if key in index and index.get(key, {}).get('state') == state:
                    skipped += 1
                    continue

                if self.agent.mark_item(item, force=True):
                    updated += 1
                    new_index[key] = {
                        'state': state,
                        'ts': int(time.time()),
                        'label': item[5]
                    }
        finally:
            progress.close()
            save_index(MOVIES_INDEX_FILE, new_index)
            clear_stop_flag(STOP_MOVIES_FILE)
            _flush_batched_notifications(force=True)

        if not canceled:
            notify(__language__(30213) % (updated, skipped, total), 2500)


class MyPlayer(xbmc.Monitor):
    def __init__(self, *args, **kwargs):
        xbmc.Monitor.__init__(self)
        self.agent = kwargs['agent']
        self.resolver = kwargs['resolver']
        self.Play = False
        log('Player Class Init')

    def _get_result_item(self, data):
        try:
            result = json.loads(data)
            return result.get('item', {}), result
        except Exception:
            return {}, {}

    def onNotification(self, sender, method, data):
        if sender != 'xbmc':
            return

        if method == 'Player.OnPlay':
            item, _ = self._get_result_item(data)
            if 'id' in item and item.get('type') in ('episode', 'movie'):
                xbmc.sleep(1000)
                self.Play = True
            return

        if method == 'Player.OnStop':
            item, result = self._get_result_item(data)
            if 'id' in item and result.get('end'):
                if item.get('type') == 'episode':
                    episode = self.resolver.get_episode_info(item['id'], 1, True)
                    if episode:
                        self.agent.mark_item(episode, force=False)
                elif item.get('type') == 'movie':
                    movie = self.resolver.get_movie_info(item['id'], 1, True)
                    if movie:
                        self.agent.mark_item(movie, force=False)

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
                episode = self.resolver.get_episode_info(item['id'], playcount, self.Play)
                if episode:
                    self.agent.mark_item(episode, force=False)
                    if playcount == 0:
                        episode[2] = -1
                        self.agent.mark_item(episode, force=False)

            elif item.get('type') == 'movie':
                movie = self.resolver.get_movie_info(item['id'], playcount, self.Play)
                if movie:
                    self.agent.mark_item(movie, force=False)

            self.Play = False
            _flush_batched_notifications(force=False)


class MyMonitor(xbmc.Monitor):
    def __init__(self, *args, **kwargs):
        xbmc.Monitor.__init__(self)
        self.action = kwargs['action']

    def onSettingsChanged(self):
        log('onSettingsChanged')
        self.action()


class Main:
    def __init__(self):
        ensure_profile_dir()
        self.agent = BetaSeriesAgent()
        if not self.agent.is_ready():
            log('addon not configured', xbmc.LOGINFO)
            return

        self.resolver = KodiLibraryResolver(self.agent)
        params = parse_params(sys.argv)
        action = params.get('action', '')
        if action:
            self.run_action(action)
        else:
            self.run_service()

    def run_action(self, action):
        sync = ManualSync(self.agent, self.resolver)

        if action == 'sync_episodes':
            sync.sync_episodes(reset=False)
            return
        if action == 'sync_movies':
            sync.sync_movies(reset=False)
            return
        if action == 'full_sync_episodes':
            sync.sync_episodes(reset=True)
            return
        if action == 'full_sync_movies':
            sync.sync_movies(reset=True)
            return
        if action == 'stop_sync_episodes':
            create_stop_flag(STOP_EPISODES_FILE)
            notify(30214, 2000)
            return
        if action == 'stop_sync_movies':
            create_stop_flag(STOP_MOVIES_FILE)
            notify(30215, 2000)
            return

        notify(__language__(30216) % action, 1500)

    def _reload_settings(self):
        self.agent = BetaSeriesAgent()
        self.resolver = KodiLibraryResolver(self.agent)

    def run_service(self):
        self.Monitor = MyMonitor(action=self._reload_settings)
        self.Player = MyPlayer(agent=self.agent, resolver=self.resolver)
        monitor = xbmc.Monitor()
        while not monitor.abortRequested():
            _flush_batched_notifications(force=False)
            if monitor.waitForAbort(1):
                break
        _flush_batched_notifications(force=True)


if __name__ == '__main__':
    log('script version %s started' % __addonversion__)
    __useragent__ = set_user_agent()
    Main()