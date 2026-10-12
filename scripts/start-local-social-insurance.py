#!/usr/bin/env python3
"""Run the workbench with this checkout's connector and existing Keychain credentials."""
import argparse
import json
import os
from pathlib import Path
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import time
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[1]
SERVER = r"""
import http from 'node:http';
const root = process.env.SIGMA_LOCAL_CONNECTOR_ROOT;
const { pathToFileURL } = await import('node:url');
const handlers = new Map();
for (const route of ['health', 'subjects', 'sync']) {
  handlers.set('/' + route, (await import(pathToFileURL(`${root}/api/${route}.mjs`))).default);
}
http.createServer(async (req, res) => {
  res.status = code => { res.statusCode = code; return res; };
  res.json = body => { res.setHeader('Content-Type', 'application/json'); res.end(JSON.stringify(body)); };
  const handler = handlers.get(req.url);
  if (!handler) return res.status(404).json({error: 'NOT_FOUND'});
  try {
    let size = 0;
    const chunks = [];
    for await (const chunk of req) {
      size += chunk.length;
      if (size > 1048576) return res.status(413).json({error: 'PAYLOAD_TOO_LARGE'});
      chunks.push(chunk);
    }
    req.body = JSON.parse(Buffer.concat(chunks).toString() || '{}');
  } catch {
    return res.status(400).json({error: 'INVALID_BODY'});
  }
  await handler(req, res);
}).listen(Number(process.env.SIGMA_LOCAL_CONNECTOR_PORT), '127.0.0.1');
"""


def keychain(service):
    result = subprocess.run(
        ['security', 'find-generic-password', '-s', service, '-w'],
        capture_output=True, text=True,
    )
    if result.returncode or not result.stdout.strip():
        raise RuntimeError(f'Keychain credential unavailable: {service}')
    return result.stdout.strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8002)
    parser.add_argument('--connector-port', type=int, default=18022)
    args = parser.parse_args()
    node = shutil.which('node')
    if not node:
        raise RuntimeError('Node.js is unavailable')
    if args.port == args.connector_port:
        raise RuntimeError('Workbench and connector ports must differ')
    for port in (args.port, args.connector_port):
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', port))

    connector_env = dict(os.environ)
    connector_env.update(
        BEISEN_APP_KEY=keychain('beisen-social-insurance-key'),
        BEISEN_APP_SECRET=keychain('beisen-social-insurance-secret'),
        CONNECTOR_TOKEN=secrets.token_urlsafe(32),
        SIGMA_LOCAL_CONNECTOR_ROOT=str(ROOT / 'social_insurance_connector'),
        SIGMA_LOCAL_CONNECTOR_PORT=str(args.connector_port),
    )
    # This development launcher must not reuse an old departure snapshot.
    for name in ('SOCIAL_INSURANCE_DIMISSION_SNAPSHOT_GZIP_BASE64', 'SOCIAL_INSURANCE_DIMISSION_SNAPSHOT_DATE'):
        connector_env.pop(name, None)
    app_env = dict(os.environ)
    app_env.update(
        SIGMA_SOCIAL_INSURANCE_CONNECTOR_URL=f'http://127.0.0.1:{args.connector_port}',
        SIGMA_SOCIAL_INSURANCE_CONNECTOR_TOKEN=connector_env['CONNECTOR_TOKEN'],
        SIGMA_SOCIAL_INSURANCE_PREFETCH_ENABLED='0',
    )
    children = []
    try:
        children.append(subprocess.Popen([node, '--input-type=module', '-e', SERVER], cwd=ROOT, env=connector_env))
        deadline = time.monotonic() + 10
        while True:
            if children[0].poll() is not None:
                raise RuntimeError('Local connector failed to start')
            try:
                with urlopen(f'http://127.0.0.1:{args.connector_port}/health', timeout=1) as response:
                    if json.load(response).get('configured'):
                        break
            except OSError:
                pass
            if time.monotonic() >= deadline:
                raise RuntimeError('Local connector startup timed out')
            time.sleep(0.1)
        children.append(subprocess.Popen(
            [sys.executable, '-m', 'uvicorn', 'bonus_platform.app:app', '--host', '127.0.0.1',
             '--port', str(args.port), '--no-access-log'], cwd=ROOT, env=app_env,
        ))
        print(f'Local workbench: http://127.0.0.1:{args.port}/social-insurance.html', flush=True)
        while all(child.poll() is None for child in children):
            time.sleep(0.5)
        return next(child.returncode for child in children if child.returncode is not None)
    finally:
        for child in children:
            if child.poll() is None:
                child.terminate()
        for child in children:
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()


if __name__ == '__main__':
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(0)
    except (RuntimeError, OSError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
