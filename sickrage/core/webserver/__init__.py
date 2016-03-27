#!/usr/bin/env python2

# Author: echel0n <sickrage.tv@gmail.com>
# URL: http://www.github.com/sickragetv/sickrage/
#
# This file is part of SickRage.
#
# SickRage is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# SickRage is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with SickRage.  If not, see <http://www.gnu.org/licenses/>.

from __future__ import unicode_literals

import os
import shutil
import threading
import webbrowser

from tornado.httpserver import HTTPServer
from tornado.ioloop import IOLoop
from tornado.web import Application, RedirectHandler, StaticFileHandler

import sickrage
from sickrage.core.helpers import create_https_certificates, generateApiKey, get_lan_ip
from sickrage.core.webserver.api import ApiHandler, KeyHandler
from sickrage.core.webserver.routes import Route
from sickrage.core.webserver.views import CalendarHandler, LoginHandler, LogoutHandler


def launch_browser(protocol=None, host=None, startport=None):
    browserurl = '{}://{}:{}/home/'.format(protocol or 'http', host, startport or 8081)

    try:
        sickrage.srLogger.info("Launching browser window")

        try:
            webbrowser.open(browserurl, 2, 1)
        except webbrowser.Error:
            webbrowser.open(browserurl, 1, 1)
    except webbrowser.Error:
        print("Unable to launch a browser")


class StaticImageHandler(StaticFileHandler):
    def initialize(self, path, default_filename=None):
        super(StaticImageHandler, self).initialize(path, default_filename)

    def get(self, path, include_body=True):
        # image cache check
        self.root = (self.root, os.path.join(sickrage.srConfig.CACHE_DIR, 'images'))[
            os.path.exists(os.path.normpath(os.path.join(sickrage.srConfig.CACHE_DIR, 'images', path)))
        ]

        # image css check
        self.root = (self.root, os.path.join(sickrage.srConfig.GUI_DIR, 'css', 'lib', 'images'))[
            os.path.exists(os.path.normpath(os.path.join(sickrage.srConfig.GUI_DIR, 'css', 'lib', 'images', path)))
        ]

        return super(StaticImageHandler, self).get(path, include_body)


class srWebServer(object):
    def __init__(self):
        super(srWebServer, self).__init__()
        self.name = "TORNADO"
        self.io_loop = IOLoop.instance()
        self.started = False

    def start(self):
        self.started = True

        threading.currentThread().setName(self.name)

        # video root
        self.video_root = None
        if sickrage.srConfig.ROOT_DIRS:
            root_dirs = sickrage.srConfig.ROOT_DIRS.split('|')
            self.video_root = root_dirs[int(root_dirs[0]) + 1]

        # web root
        if sickrage.srConfig.WEB_ROOT:
            sickrage.srConfig.WEB_ROOT = sickrage.srConfig.WEB_ROOT = (
                '/' + sickrage.srConfig.WEB_ROOT.lstrip('/').strip('/'))

        # api root
        if not sickrage.srConfig.API_KEY:
            sickrage.srConfig.API_KEY = generateApiKey()
        self.api_root = r'%s/api/%s' % (sickrage.srConfig.WEB_ROOT, sickrage.srConfig.API_KEY)

        # tornado setup
        if sickrage.srConfig.ENABLE_HTTPS:
            # If either the HTTPS certificate or key do not exist, make some self-signed ones.
            if not (sickrage.srConfig.HTTPS_CERT and os.path.exists(sickrage.srConfig.HTTPS_CERT)) or not (
                        sickrage.srConfig.HTTPS_KEY and os.path.exists(sickrage.srConfig.HTTPS_KEY)):
                if not create_https_certificates(sickrage.srConfig.HTTPS_CERT, sickrage.srConfig.HTTPS_KEY):
                    sickrage.srLogger.info("Unable to create CERT/KEY files, disabling HTTPS")
                    sickrage.srConfig.ENABLE_HTTPS = False

            if not (os.path.exists(sickrage.srConfig.HTTPS_CERT) and os.path.exists(sickrage.srConfig.HTTPS_KEY)):
                sickrage.srLogger.warning("Disabled HTTPS because of missing CERT and KEY files")
                sickrage.srConfig.ENABLE_HTTPS = False

        # Load the app
        self.app = Application([],
                               debug=sickrage.srConfig.DEBUG,
                               autoreload=False,
                               gzip=sickrage.srConfig.WEB_USE_GZIP,
                               xheaders=sickrage.srConfig.HANDLE_REVERSE_PROXY,
                               cookie_secret=sickrage.srConfig.WEB_COOKIE_SECRET,
                               login_url='%s/login/' % sickrage.srConfig.WEB_ROOT,
                               )

        # Main Handlers
        self.app.add_handlers('.*$', [
            # webapi handler
            (r'%s(/?.*)' % self.api_root, ApiHandler),

            # webapi key retrieval
            (r'%s/getkey(/?.*)' % sickrage.srConfig.WEB_ROOT, KeyHandler),

            # webapi builder redirect
            (r'%s/api/builder' % sickrage.srConfig.WEB_ROOT, RedirectHandler,
             {"url": sickrage.srConfig.WEB_ROOT + '/apibuilder/'}),

            # webui login/logout handlers
            (r'%s/login(/?)' % sickrage.srConfig.WEB_ROOT, LoginHandler),
            (r'%s/logout(/?)' % sickrage.srConfig.WEB_ROOT, LogoutHandler),

            # webui handlers
        ] + Route.get_routes(sickrage.srConfig.WEB_ROOT))

        # Web calendar handler (Needed because option Unprotected calendar)
        self.app.add_handlers('.*$', [
            (r'%s/calendar' % sickrage.srConfig.WEB_ROOT, CalendarHandler),
        ])

        # Static File Handlers
        self.app.add_handlers(".*$", [
            # favicon
            (r'%s/(favicon\.ico)' % sickrage.srConfig.WEB_ROOT, StaticFileHandler,
             {"path": os.path.join(sickrage.srConfig.GUI_DIR, 'images/ico/favicon.ico')}),

            # images
            (r'%s.*?/images/(.*)' % sickrage.srConfig.WEB_ROOT, StaticImageHandler,
             {"path": os.path.join(sickrage.srConfig.GUI_DIR, 'images')}),

            # css
            (r'%s/css/(.*)' % sickrage.srConfig.WEB_ROOT, StaticFileHandler,
             {"path": os.path.join(sickrage.srConfig.GUI_DIR, 'css')}),

            # scss
            (r'%s/scss/(.*)' % sickrage.srConfig.WEB_ROOT, StaticFileHandler,
             {"path": os.path.join(sickrage.srConfig.GUI_DIR, 'scss')}),

            # fonts
            (r'%s/fonts/(.*)' % sickrage.srConfig.WEB_ROOT, StaticFileHandler,
             {"path": os.path.join(sickrage.srConfig.GUI_DIR, 'fonts')}),

            # javascript
            (r'%s/js/(.*)' % sickrage.srConfig.WEB_ROOT, StaticFileHandler,
             {"path": os.path.join(sickrage.srConfig.GUI_DIR, 'js')}),

            # videos
        ] + [(r'%s/videos/(.*)' % sickrage.srConfig.WEB_ROOT, StaticFileHandler,
              {"path": self.video_root})])

        self.server = HTTPServer(self.app)
        if sickrage.srConfig.ENABLE_HTTPS:
            self.server.ssl_options = {"certfile": sickrage.srConfig.HTTPS_CERT, "keyfile": sickrage.srConfig.HTTPS_KEY}
        self.server.listen(sickrage.srConfig.WEB_PORT, None)

        # launch browser window
        if all([not sickrage.NOLAUNCH, sickrage.srConfig.LAUNCH_BROWSER]):
            threading.Thread(None,
                             lambda: launch_browser(
                                 ('http', 'https')[sickrage.srConfig.ENABLE_HTTPS],
                                 get_lan_ip(),
                                 sickrage.srConfig.WEB_PORT
                             )).start()

        # clear mako cache folder
        makocache = os.path.join(sickrage.srConfig.CACHE_DIR, 'mako')
        if os.path.isdir(makocache):
            shutil.rmtree(makocache)

        sickrage.srLogger.info(
            "SiCKRAGE STARTED :: VERSION:[{}] CONFIG:[{}] URL:[{}://{}:{}/]"
                .format(sickrage.srCore.VERSION,
                        sickrage.CONFIG_FILE,
                        ('http', 'https')[sickrage.srConfig.ENABLE_HTTPS],
                        get_lan_ip(), sickrage.srConfig.WEB_PORT)
        )

        self.io_loop.start()

    def shutdown(self):
        if self.started:
            self.server.stop()
            self.io_loop.stop()
            self.started = False
