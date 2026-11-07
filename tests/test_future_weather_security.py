"""Offline checks for the optional fixed-destination weather adapter."""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.error import HTTPError

import pytest

from gondola.future import weather as W


def test_weather_does_not_follow_redirects(monkeypatch):
    requested = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requested.append(self.path)
            if self.path.startswith('/forecast'):
                self.send_response(302)
                self.send_header('Location', '/redirected')
            else:
                self.send_response(200)
            self.end_headers()

        def log_message(self, *args):
            pass

    server = HTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        monkeypatch.setattr(W, 'URL', f'http://127.0.0.1:{server.server_port}/forecast?lat={{lat}}&lon={{lon}}')
        with pytest.raises(HTTPError) as error:
            W._fetch()
        assert error.value.code == 302
        assert len(requested) == 1 and requested[0].startswith('/forecast')
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


def test_weather_fetch_limits_response_size(monkeypatch):
    class Response:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def read(self, size):
            return b' ' * size
    class Opener:
        def open(self, url, timeout):
            assert url.startswith('https://api.open-meteo.com/')
            return Response()
    monkeypatch.setattr(W.urllib.request, 'build_opener', lambda *args: Opener())
    with pytest.raises(ValueError, match='too large'):
        W._fetch()
    assert W.daily_forecast(fetch=lambda: json.loads('{}')) == {}
