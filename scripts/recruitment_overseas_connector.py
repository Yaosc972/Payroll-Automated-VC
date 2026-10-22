"""Serve only recruitment HR reads on an authorized machine with Ego sessions.

Bind to loopback behind the company HTTPS gateway. No browser cookies or HR
credentials leave the runtime. Launch only after the endpoint is approved.
"""
import argparse
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from threading import Lock

from bonus_platform.engine.recruitment_overseas import BrowserClient, _month, validate_snapshot
from bonus_platform.engine.recruitment_remote import PATH, MAX_RESPONSE

BUSY = Lock()
MAX_REQUEST = 512 * 1024


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # Never record source payloads or authorization headers.

    def reply(self, status, value):
        content = json.dumps(value, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def do_POST(self):
        token = os.getenv('SIGMA_RECRUITMENT_OVERSEAS_CONNECTOR_TOKEN', '')
        if not token or not hmac.compare_digest(self.headers.get('Authorization', ''), 'Bearer ' + token):
            return self.reply(401, {'detail': 'Unauthorized'})
        if self.path != PATH:
            return self.reply(404, {'detail': 'Not found'})
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if self.headers.get('Transfer-Encoding') or not 0 < length <= MAX_REQUEST:
                raise ValueError()
            value = json.loads(self.rfile.read(length))
            if not isinstance(value, dict) or set(value) != {'month', 'jobNumbers', 'offerCodes'}:
                raise ValueError()
            _month(value['month'])
            for key in ('jobNumbers', 'offerCodes'):
                if (not isinstance(value[key], list) or len(value[key]) > 5000
                        or any(not isinstance(n, str) or not n or len(n) > 180 for n in value[key])):
                    raise ValueError()
        except (ValueError, TypeError, KeyError):
            return self.reply(400, {'detail': 'Invalid query scope'})
        if not BUSY.acquire(blocking=False):
            return self.reply(409, {'detail': 'Busy'})
        try:
            # Explicit BrowserClient prevents recursive remote calls on this machine.
            payload = validate_snapshot(BrowserClient().fetch(value['month'], value['jobNumbers'], value['offerCodes']), value['month'])
            if len(json.dumps(payload).encode()) > MAX_RESPONSE:
                raise ValueError()
            return self.reply(200, payload)
        except Exception:
            return self.reply(424, {'detail': 'HR browser session or query unavailable'})
        finally:
            BUSY.release()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8193)
    args = parser.parse_args()
    if not os.getenv('SIGMA_RECRUITMENT_OVERSEAS_CONNECTOR_TOKEN'):
        raise RuntimeError('Configure the connector token in the runtime secret store')
    ThreadingHTTPServer(('127.0.0.1', args.port), Handler).serve_forever()


if __name__ == '__main__':
    main()
