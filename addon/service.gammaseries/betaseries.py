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

_notification_items = {}
_notification_order = []
_notification_last_ts = 0
_notification_bulk_mode = False
_notification_bulk_started_ts = 0
_notification_started_notice_shown = False
_notification_window_seconds = 1.5
_notification_bulk_threshold = 3

EPISODES_INDEX_FILE = os.path.join(__profile__, 'episodes_sync_index.json')
MOVIES_INDEX_FILE = os.path.join(__profile__, 'movies_sync_index.json')
EPISODES_PROGRESS_FILE = os.path.join(__profile__, 'episodes_sync_progress.json')
MOVIES_PROGRESS_FILE = os.path.join(__profile__, 'movies_sync_progress.json')
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
        log('%s failed for %s - unknown API error' % (
            context, format_item_label(item)
        ), xbmc.LOGERROR)


def _notification_item_key(item):
    if item[6] == 'episode':
        return 'episode_%s' % str(item[1])
    return 'movie_%s' % str(item[0])


def _notification_action_for_item(item):
    if item[6] == 'movie':
        return 'unwatched' if item[2] == 0 else 'watched'
    if item[2] == 0:
        return 'unwatched'
    if item[2] == -1:
        return 'downloaded'
    return 'watched'


def _queue_notification_item(item):
    global _notification_items, _notification_order, _notification_last_ts, _notification_bulk_mode

    key = _notification_item_key(item)
    if key not in _notification_items:
        _notification_order.append(key)

    _notification_items[key] = {
        'key': key,
        'media_type': item[6],
        'action': _notification_action_for_item(item),
        'label': format_item_label(item),
        'ts': time.time()
    }
    _notification_last_ts = time.time()

    if len(_notification_items) >= _notification_bulk_threshold:
        _notification_bulk_mode = True


def start_mass_update_notification(prefix=None):
    global _notification_bulk_mode, _notification_bulk_started_ts, _notification_started_notice_shown
    _notification_bulk_mode = True
    _notification_bulk_started_ts = time.time()
    if not _notification_started_notice_shown:
        notify(prefix or 30200, 1200)
        _notification_started_notice_shown = True


def _notification_message(media_type, action, count):
    key = '%s_%s' % (media_type, action)
    if key == 'episode_watched':
        return (__language__(30218) % count) if count > 1 else __language__(30014)
    if key == 'episode_unwatched':
        return (__language__(30219) % count) if count > 1 else __language__(30015)
    if key == 'episode_downloaded':
        return (__language__(30220) % count) if count > 1 else __language__(30101)
    if key == 'movie_watched':
        return (__language__(30221) % count) if count > 1 else __language__(30016)
    if key == 'movie_unwatched':
        return (__language__(30222) % count) if count > 1 else __language__(30017)
    return None


def _single_notification_message(event):
    if event['media_type'] == 'episode':
        if event['action'] == 'watched':
            return 'Épisode mis à jour : vu'
        if event['action'] == 'unwatched':
            return 'Épisode mis à jour : non vu'
        if event['action'] == 'downloaded':
            return 'Épisode mis à jour : téléchargé'
    elif event['media_type'] == 'movie':
        if event['action'] == 'watched':
            return 'Film mis à jour : vu'
        if event['action'] == 'unwatched':
            return 'Film mis à jour : non vu'
    return None


def _reset_notifications():
    global _notification_items, _notification_order, _notification_last_ts
    global _notification_bulk_mode, _notification_bulk_started_ts, _notification_started_notice_shown

    _notification_items = {}
    _notification_order = []
    _notification_last_ts = 0
    _notification_bulk_mode = False
    _notification_bulk_started_ts = 0
    _notification_started_notice_shown = False


def _collect_final_notification_events():
    events = []
    for key in _notification_order:
        event = _notification_items.get(key)
        if event:
            events.append(event)
    return events


def _group_bulk_events(events):
    grouped = []
    for ev in events:
        if grouped and grouped[-1]['media_type'] == ev['media_type'] and grouped[-1]['action'] == ev['action']:
            grouped[-1]['count'] += 1
        else:
            grouped.append({
                'media_type': ev['media_type'],
                'action': ev['action'],
                'count': 1
            })
    return grouped


def _flush_batched_notifications(force=False):
    global _notification_last_ts

    if not _notification_items:
        return

    now = time.time()
    if not force and (now - _notification_last_ts) < _notification_window_seconds:
        return

    events = _collect_final_notification_events()
    if not events:
        _reset_notifications()
        return

    if not _notification_bulk_mode and len(events) == 1:
        msg = _single_notification_message(events[0])
        if msg:
            notify(msg, 1200)
        _reset_notifications()
        return

    grouped = _group_bulk_events(events)
    if len(grouped) > 2:
        summary = {}
        order = []
        for g in grouped:
            key = '%s_%s' % (g['media_type'], g['action'])
            if key not in summary:
                summary[key] = {
                    'media_type': g['media_type'],
                    'action': g['action'],
                    'count': 0
                }
                order.append(key)
            summary[key]['count'] += g['count']
        grouped = [summary[key] for key in order[:2]]

    for g in grouped:
        msg = _notification_message(g['media_type'], g['action'], g['count'])
        if msg:
            notify(msg, 1500)

    _reset_notifications()


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

    return "Mozilla/5.0 (compatible; %s; %s; %s/%s)" % (__platform__, version, __addonid__, __addonversion__)


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
        return connection.read(), 200

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
            log('HTTP error %s for %s: %s - body: %s' % (
                str(getattr(e, 'code', 'n/a')),
                url,
                str(getattr(e, 'reason', 'n/a')),
                response_text[:500]
            ), xbmc.LOGERROR)

        return response_body, getattr(e, 'code', None)

    except Exception as e:
        log('request error for %s: %s' % (url, repr(e)), xbmc.LOGERROR)
        raise


def get_json(url, urldata='', method='GET'):
    response, status = get_urldata(url, urldata, method)
    data = json.loads(response) if response else {}
    if status is not None and status >= 400 and not data.get('errors'):
        data['errors'] = [{'code': -1, 'text': 'HTTP %s' % status}]
    return data


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


def load_json_file(filepath, default_value):
    ensure_profile_dir()
    try:
        with open(filepath, 'r') as f:
            data = json.loads(f.read())
            if data is not None:
                return data
    except Exception:
        pass
    return default_value


def save_json_file(filepath, data):
    ensure_profile_dir()
    with open(filepath, 'w') as f:
        f.write(json.dumps(data))


def load_index(filepath):
    data = load_json_file(filepath, {})
    return data if isinstance(data, dict) else {}


def save_index(filepath, data):
    save_json_file(filepath, data)


def load_progress(filepath):
    data = load_json_file(filepath, {})
    return data if isinstance(data, dict) else {}


def save_progress(filepath, data):
    save_json_file(filepath, data)


def clear_progress(filepath):
    try:
        if os.path.exists(filepath):
            os.remove(filepath)
    except Exception:
        pass


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
        self.apiver = '3.0'
        self.watch_date_endpoint_unavailable = False
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
        return False

    def _build_mark_request(self, item):
        service = self.service
        if item[6] == 'movie':
            url = service[1] + '/movies/movie'
            urldata = {'v': self.apiver, 'key': service[2], 'token': service[6], 'id': item[0], 'state': item[2]}
            method = 'POST'
            act = 'not watched' if item[2] == 0 else 'watched'
            watch_date = item[7] if len(item) > 7 else None
            if item[2] != 0 and watch_date:
                urldata['date'] = watch_date
            return url, urldata, method, act

        urldata = {'v': self.apiver, 'key': service[2], 'token': service[6], 'thetvdb_id': item[1]}
        if service[11]:
            urldata['bulk'] = 1
        if item[2] == 0:
            return service[1] + '/episodes/watched', urldata, 'DELETE', 'not watched'
        if item[2] == -1:
            return service[1] + '/episodes/downloaded', urldata, 'POST', 'downloaded'
        watch_date = item[7] if len(item) > 7 else None
        if watch_date:
            urldata['date'] = watch_date
        return service[1] + '/episodes/watched', urldata, 'POST', 'watched'

    def correct_episode_watch_date(self, item):
        service = self.service
        if self.watch_date_endpoint_unavailable:
            return False

        watch_date = item[7] if len(item) > 7 else None
        bs_episode_id = item[8] if len(item) > 8 else None
        if not watch_date or not bs_episode_id:
            log('watch date correction skipped for %s: watch_date=%r bs_episode_id=%r' % (
                format_item_label(item), watch_date, bs_episode_id
            ), xbmc.LOGWARNING)
            return False

        url = service[1] + '/episodes/watch_date'
        urldata = {
            'v': self.apiver, 'key': service[2], 'token': service[6],
            'id': bs_episode_id, 'new_date': watch_date
        }
        try:
            data = get_json(url, urldata, 'POST')
        except Exception:
            self.service = self._service_fail(service, False)
            log('watch date correction failed for %s' % format_item_label(item), xbmc.LOGERROR)
            return False

        errors = data.get('errors')
        if errors:
            code = errors[0]['code']
            if code == 2001:
                service[6] = ''
            if code == -1 and 'HTTP 404' in str(errors[0].get('text', '')):
                self.watch_date_endpoint_unavailable = True
                log('episodes/watch_date endpoint returned 404 - disabling further attempts for this run', xbmc.LOGWARNING)
            log_api_error(item, 'WatchDate', data)
            return False

        log('%s watch date corrected to %s' % (format_item_label(item), watch_date), xbmc.LOGINFO)
        return True

    def _queue_success_notification(self, item):
        if not self.service[15]:
            return
        _queue_notification_item(item)

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
            code = errors[0]['code']

            if code == 2001:
                log_api_error(item, 'Sync', data)
                service[6] = ''
                return False

            if item[6] == 'episode' and item[2] == 0 and code == 2005:
                log('episode already not watched on BetaSeries: %s' % format_item_label(item), xbmc.LOGINFO)
                self._queue_success_notification(item)
                _flush_batched_notifications(force=False)
                return True

            if 'date' in urldata:
                log_api_error(item, 'Sync (with date, retrying without)', data)
                retry_urldata = dict(urldata)
                del retry_urldata['date']
                try:
                    retry_data = get_json(url, retry_urldata, method)
                except Exception:
                    self.service = self._service_fail(service, False)
                    log('sync retry (without date) failed for %s' % format_item_label(item), xbmc.LOGERROR)
                    return False

                retry_errors = retry_data.get('errors')
                if not retry_errors:
                    self._queue_success_notification(item)
                    _flush_batched_notifications(force=False)
                    log('%s marked as %s (date param rejected by API, retried without date)' % (format_item_label(item), act), xbmc.LOGWARNING)
                    return True

                data = retry_data
                errors = retry_errors
                code = errors[0]['code']

            if item[6] == 'episode' and item[2] not in (0, -1) and self.correct_episode_watch_date(item):
                log('episode already watched on BetaSeries, watch date corrected instead: %s' % format_item_label(item), xbmc.LOGINFO)
                self._queue_success_notification(item)
                _flush_batched_notifications(force=False)
                return True

            log_api_error(item, 'Sync', data)
            return False

        if item[6] == 'episode' and item[2] not in (0, -1) and (item[7] if len(item) > 7 else None):
            # BetaSeries silently ignores the "date" param on /episodes/watched when the
            # episode is already marked watched - force it via the dedicated endpoint too.
            self.correct_episode_watch_date(item)

        self._queue_success_notification(item)
        _flush_batched_notifications(force=False)
        log('%s marked as %s' % (format_item_label(item), act), xbmc.LOGINFO)
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
        query = '?v=3.0&key=%s&title=%s' % (self.service[2], urllib.parse.quote(showtitle))
        data = get_json(url + query, '', 'GET')
        best = self._pick_best_show(data.get('shows', []), showtitle, self._safe_int_year(show_year))
        if best:
            return best.get('thetvdb_id')
        return ''

    def _search_episode_ids(self, tvdbid, season, episode_num):
        url = self.service[1] + '/shows/episodes'
        query = '?v=3.0&key=%s&thetvdb_id=%s&season=%s&episode=%s' % (
            self.service[2], str(tvdbid), str(season), str(episode_num)
        )
        data = get_json(url + query, '', 'GET')
        episodes = data.get('episodes', [])
        if episodes:
            return episodes[0].get('id'), episodes[0].get('thetvdb_id')
        return '', ''

    def _norm_watch_date(self, lastplayed):
        if not lastplayed or lastplayed == '1601-01-01 00:00:00':
            return None
        return lastplayed

    def get_episode_status_text(self, episodeid, playcount):
        try:
            ep = kodi_jsonrpc(
                'VideoLibrary.GetEpisodeDetails',
                {'episodeid': episodeid, 'properties': ['lastplayed']}
            )['result']['episodedetails']
            lastplayed = ep.get('lastplayed') or ''
        except Exception:
            lastplayed = ''

        if int(playcount or 0) > 0:
            if lastplayed and lastplayed != '1601-01-01 00:00:00':
                return __language__(30232) % lastplayed
            return __language__(30230)
        return __language__(30231)

    def get_episode_info(self, episodeid, playcount, playstatus):
        showtitle = ''
        season = None
        episode_num = None
        show_year = None
        tvdbid = ''
        tvdbepid = ''
        lastplayed = ''

        try:
            ep = kodi_jsonrpc(
                'VideoLibrary.GetEpisodeDetails',
                {'episodeid': episodeid, 'properties': ['tvshowid', 'showtitle', 'season', 'episode', 'uniqueid', 'lastplayed']}
            )['result']['episodedetails']
            showtitle = ep.get('showtitle', '')
            season = ep.get('season')
            episode_num = ep.get('episode')
            tvshowid = ep.get('tvshowid')
            lastplayed = ep.get('lastplayed') or ''

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
            bs_episode_id, tvdbepid = self._search_episode_ids(tvdbid, season, episode_num)
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
        watch_date = self._norm_watch_date(lastplayed)
        return [
            int(tvdbid), int(tvdbepid), int(playcount), bool(playstatus), showtitle, epname, 'episode',
            watch_date, bs_episode_id or None
        ]

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

    def get_movie_status_text(self, movieid, playcount):
        try:
            movie = kodi_jsonrpc(
                'VideoLibrary.GetMovieDetails',
                {'movieid': movieid, 'properties': ['lastplayed']}
            )['result']['moviedetails']
            lastplayed = movie.get('lastplayed') or ''
        except Exception:
            lastplayed = ''

        if int(playcount or 0) > 0:
            if lastplayed and lastplayed != '1601-01-01 00:00:00':
                return __language__(30232) % lastplayed
            return __language__(30230)
        return __language__(30231)

    def get_movie_info(self, movieid, playcount, playstatus):
        try:
            movie = kodi_jsonrpc(
                'VideoLibrary.GetMovieDetails',
                {'movieid': movieid, 'properties': ['title', 'originaltitle', 'imdbnumber', 'uniqueid', 'year', 'lastplayed']}
            )['result']['moviedetails']
        except Exception:
            log("could not get movie details", xbmc.LOGERROR)
            return False

        uniqueid = movie.get('uniqueid', {}) or {}
        imdbid = uniqueid.get('imdb') or movie.get('imdbnumber') or ''
        tmdbid = uniqueid.get('tmdb') or ''
        moviename = movie.get('originaltitle') or movie.get('title') or ''
        movieyear = movie.get('year')
        watch_date = self._norm_watch_date(movie.get('lastplayed') or '')

        if not moviename:
            return False

        if tmdbid or imdbid:
            try:
                movie_bs_id, movie_tmdb_id = self._lookup_movie_by_ids(tmdbid, imdbid)
                return [int(movie_bs_id), int(movie_tmdb_id), int(playcount), bool(playstatus), '', moviename, 'movie', watch_date]
            except Exception:
                log("direct movie lookup failed for %s, fallback to search" % moviename, xbmc.LOGERROR)

        try:
            movie_bs_id, movie_tmdb_id = self._search_movie_ids(moviename, movieyear)
            if not movie_bs_id:
                log("no BetaSeries movie match for '%s' (%s)" % (moviename, str(movieyear)), xbmc.LOGERROR)
                return False

            return [int(movie_bs_id), int(movie_tmdb_id or 0), int(playcount), bool(playstatus), '', moviename, 'movie', watch_date]
        except Exception:
            log("could not fetch movie BetaSeries id : %s" % moviename, xbmc.LOGERROR)
            return False


class ManualSync:
    def __init__(self, agent, resolver):
        self.agent = agent
        self.resolver = resolver
        self.monitor = xbmc.Monitor()

    def _make_progress_lines(self, media_label, current, total, updated, skipped, errors_count, current_label):
        percent = int((float(current) / float(total)) * 100) if total else 0
        line1 = '%s : %d / %d (%d%%)' % (media_label, current, total, percent)
        line2 = __language__(30233) % (updated, skipped, errors_count)
        line3 = safe_label(current_label or __language__(30204))
        return line1, line2, line3

    def _should_stop(self, stop_file, progress_dialog):
        if stop_requested(stop_file, self.monitor):
            return True
        if progress_dialog and progress_dialog.iscanceled():
            create_stop_flag(stop_file)
            return True
        return False

    def _resume_position(self, entries, progress_key, key_getter):
        if not progress_key:
            return 0
        for idx, entry in enumerate(entries):
            if key_getter(entry) == progress_key:
                return idx + 1
        return 0

    def sync_episodes(self, reset=False):
        clear_stop_flag(STOP_EPISODES_FILE)
        index = {} if reset else load_index(EPISODES_INDEX_FILE)
        progress_state = {} if reset else load_progress(EPISODES_PROGRESS_FILE)

        data = kodi_jsonrpc('VideoLibrary.GetEpisodes', {'properties': ['playcount', 'showtitle', 'season', 'episode']})
        episodes = data.get('result', {}).get('episodes', [])

        def entry_key(ep):
            return 'episodeid_%s' % str(ep.get('episodeid'))

        start_mass_update_notification(__language__(30201))
        start_index = self._resume_position(episodes, progress_state.get('last_processed_key'), entry_key)
        entries = episodes[start_index:]

        total = len(episodes)
        updated = 0
        skipped = 0
        errors_count = 0
        new_index = dict(index)
        progress = SyncProgressDialog(__addonname__)
        progress.create(__language__(30201), __language__(30204), '%d / %d' % (start_index, total))
        canceled = False

        try:
            for pos, ep in enumerate(entries, start_index + 1):
                episodeid = ep.get('episodeid')
                playcount = int(ep.get('playcount') or 0)
                status_text = self.resolver.get_episode_status_text(episodeid, playcount)
                current_label = '%s - S%02dE%02d | %s' % (
                    ep.get('showtitle', __language__(30208)),
                    int(ep.get('season') or 0),
                    int(ep.get('episode') or 0),
                    status_text
                )
                line1, line2, line3 = self._make_progress_lines(__language__(30205), pos, total, updated, skipped, errors_count, current_label)
                progress.update(pos, total, line1, line2, line3)

                if self._should_stop(STOP_EPISODES_FILE, progress):
                    canceled = True
                    notify(30210, 2000)
                    break

                progress_state['last_processed_key'] = entry_key(ep)
                progress_state['last_position'] = pos
                progress_state['remaining'] = max(total - pos, 0)
                save_progress(EPISODES_PROGRESS_FILE, progress_state)

                item = self.resolver.get_episode_info(episodeid, playcount, False)
                if not item:
                    errors_count += 1
                    continue

                key = str(item[1])
                state = item[2]
                watch_date = item[7] if len(item) > 7 else None

                if not index.get(key, {}).get('downloaded'):
                    downloaded_item = list(item)
                    downloaded_item[2] = -1
                    if self.agent.mark_item(downloaded_item, force=True):
                        updated += 1
                        new_index[key] = dict(new_index.get(key, index.get(key, {})))
                        new_index[key]['downloaded'] = True
                        save_index(EPISODES_INDEX_FILE, new_index)
                    else:
                        errors_count += 1

                if key in index and index.get(key, {}).get('state') == state:
                    if state == 1 and watch_date and index.get(key, {}).get('date') != watch_date:
                        if self.agent.correct_episode_watch_date(item):
                            updated += 1
                            new_index[key] = dict(new_index.get(key, index[key]))
                            new_index[key]['date'] = watch_date
                            new_index[key]['ts'] = int(time.time())
                            save_index(EPISODES_INDEX_FILE, new_index)
                        else:
                            errors_count += 1
                    else:
                        skipped += 1
                    continue

                if self.agent.mark_item(item, force=True):
                    updated += 1
                    new_index[key] = dict(new_index.get(key, {}))
                    new_index[key].update({
                        'state': state,
                        'ts': int(time.time()),
                        'label': item[5],
                        'show': item[4],
                        'date': watch_date
                    })
                    save_index(EPISODES_INDEX_FILE, new_index)
                else:
                    errors_count += 1
        finally:
            progress.close()
            save_index(EPISODES_INDEX_FILE, new_index)
            clear_stop_flag(STOP_EPISODES_FILE)
            _flush_batched_notifications(force=True)

        if canceled:
            return

        clear_progress(EPISODES_PROGRESS_FILE)
        notify(__language__(30234) % (updated, skipped, errors_count), 3000)

    def sync_movies(self, reset=False):
        clear_stop_flag(STOP_MOVIES_FILE)
        index = {} if reset else load_index(MOVIES_INDEX_FILE)
        progress_state = {} if reset else load_progress(MOVIES_PROGRESS_FILE)

        data = kodi_jsonrpc('VideoLibrary.GetMovies', {'properties': ['playcount', 'title', 'originaltitle']})
        movies = data.get('result', {}).get('movies', [])

        def entry_key(mv):
            return 'movieid_%s' % str(mv.get('movieid'))

        start_mass_update_notification(__language__(30202))
        start_index = self._resume_position(movies, progress_state.get('last_processed_key'), entry_key)
        entries = movies[start_index:]

        total = len(movies)
        updated = 0
        skipped = 0
        errors_count = 0
        new_index = dict(index)
        progress = SyncProgressDialog(__addonname__)
        progress.create(__language__(30202), __language__(30204), '%d / %d' % (start_index, total))
        canceled = False

        try:
            for pos, mv in enumerate(entries, start_index + 1):
                movieid = mv.get('movieid')
                playcount = int(mv.get('playcount') or 0)
                status_text = self.resolver.get_movie_status_text(movieid, playcount)
                current_label = '%s | %s' % (
                    mv.get('originaltitle') or mv.get('title') or __language__(30209),
                    status_text
                )
                line1, line2, line3 = self._make_progress_lines(__language__(30206), pos, total, updated, skipped, errors_count, current_label)
                progress.update(pos, total, line1, line2, line3)

                if self._should_stop(STOP_MOVIES_FILE, progress):
                    canceled = True
                    notify(30211, 2000)
                    break

                progress_state['last_processed_key'] = entry_key(mv)
                progress_state['last_position'] = pos
                progress_state['remaining'] = max(total - pos, 0)
                save_progress(MOVIES_PROGRESS_FILE, progress_state)

                item = self.resolver.get_movie_info(movieid, playcount, False)
                if not item:
                    errors_count += 1
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
                    save_index(MOVIES_INDEX_FILE, new_index)
                else:
                    errors_count += 1
        finally:
            progress.close()
            save_index(MOVIES_INDEX_FILE, new_index)
            clear_stop_flag(STOP_MOVIES_FILE)
            _flush_batched_notifications(force=True)

        if canceled:
            return

        clear_progress(MOVIES_PROGRESS_FILE)
        notify(__language__(30235) % (updated, skipped, errors_count), 3000)


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

    def sync_recently_added(self):
        try:
            log('Synchronisation des nouveautés issues du scraping avec états (récupéré/lu/non lu)...')
            
            # Épisodes récents
            episodes_data = kodi_jsonrpc(
                'VideoLibrary.GetRecentlyAddedEpisodes',
                {'properties': ['playcount', 'showtitle', 'season', 'episode'], 'limits': {'start': 0, 'end': 250}}
            )
            for ep in episodes_data.get('result', {}).get('episodes', []):
                episodeid = ep.get('episodeid')
                playcount = int(ep.get('playcount') or 0)
                
                # Récupère les infos de l'épisode (playstatus est basé sur playcount > 0)
                playstatus = (playcount > 0)
                episode = self.resolver.get_episode_info(episodeid, playcount, playstatus)
                
                if episode:
                    # 1. Marquer d'abord l'épisode comme récupéré/téléchargé sur BetaSeries (état -1)
                    episode[2] = -1 
                    self.agent.mark_item(episode, force=False)
                    
                    # 2. Si l'épisode a déjà été lu dans Kodi (playcount > 0), mettre à jour l'état à lu (1)
                    if playcount > 0:
                        episode[2] = 1
                        self.agent.mark_item(episode, force=False)

            # Films récents (les films gèrent l'état vu / non vu)
            movies_data = kodi_jsonrpc(
                'VideoLibrary.GetRecentlyAddedMovies',
                {'properties': ['playcount', 'title', 'originaltitle'], 'limits': {'start': 0, 'end': 15}}
            )
            for mv in movies_data.get('result', {}).get('movies', []):
                movieid = mv.get('movieid')
                playcount = int(mv.get('playcount') or 0)
                movie = self.resolver.get_movie_info(movieid, playcount, (playcount > 0))
                if movie:
                    self.agent.mark_item(movie, force=False)

            _flush_batched_notifications(force=True)
        except Exception as e:
            log('Erreur lors de la synchro post-scraping : %s' % repr(e), xbmc.LOGERROR)
    
    def onNotification(self, sender, method, data):
        if sender != 'xbmc':
            return

        if method == 'VideoLibrary.OnScanFinished':
            log('Fin du scan de la médiathèque détectée.')
            self.sync_recently_added()
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
        if action == 'mark_downloaded':
            self.mark_focused_item_downloaded()
            return

        notify(__language__(30216) % action, 1500)

    def mark_focused_item_downloaded(self):
        item_id_str = xbmc.getInfoLabel('Container.ListItem(0).DBID')
        item_type = xbmc.getInfoLabel('Container.ListItem(0).DBType')
        
        if not item_id_str or not item_id_str.isdigit():
            notify("Aucun élément sélectionné", 1000)
            return

        item_id = int(item_id_str)

        if item_type == 'episode':
            item = self.resolver.get_episode_info(item_id, playcount=0, playstatus=False)
            if item:
                item[2] = -1  # Force l'état à téléchargé / récupéré
                if self.agent.mark_item(item, force=True):
                    notify("Épisode marqué comme récupéré", 1200)
                else:
                    notify("Erreur lors de la synchronisation", 1200)
        elif item_type == 'movie':
            item = self.resolver.get_movie_info(item_id, playcount=0, playstatus=False)
            if item:
                if self.agent.mark_item(item, force=True):
                    notify("Film mis à jour", 1200)

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