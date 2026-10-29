#!/usr/bin/env python3
"""Exercise HomeSphere using an owner login; only delete this script's test files."""
import argparse
from getpass import getpass
import hashlib
import http.client
from http.cookies import SimpleCookie
import json
import re
import sys
from urllib.parse import urlsplit
from uuid import uuid4


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://localhost:8080')
    parser.add_argument('--username')
    parser.add_argument('--password-stdin', action='store_true')
    args = parser.parse_args()
    target = urlsplit(args.url)
    if target.scheme not in {'http', 'https'} or not target.hostname or target.path not in {'', '/'}:
        parser.error('Provide an application URL such as http://localhost:8080')
    base = args.url.rstrip('/')
    connection = http.client.HTTPSConnection if target.scheme == 'https' else http.client.HTTPConnection
    cookies = SimpleCookie()

    def request(method, path, body=None, headers=None):
        conn = connection(target.hostname, target.port, timeout=60)
        fields = dict(headers or {})
        if cookies:
            fields['Cookie'] = '; '.join(f'{key}={item.value}' for key, item in cookies.items())
        if method not in {'GET', 'HEAD', 'OPTIONS'}:
            fields.setdefault('Origin', base)
        try:
            conn.request(method, path, body=body, headers=fields)
            response = conn.getresponse()
            for key, value in response.getheaders():
                if key.lower() == 'set-cookie':
                    update = SimpleCookie(value)
                    for name, item in update.items():
                        if item['max-age'] == '0':
                            cookies.pop(name, None)
                        else:
                            cookies[name] = item.value
            return response.status, response.read(), {k.lower(): v for k, v in response.getheaders()}
        finally:
            conn.close()

    def check(condition, message):
        if not condition:
            raise RuntimeError(message)
        print('PASS:', message, flush=True)

    temporary_ids = []
    logged_in = False
    try:
        status, page, _ = request('GET', '/')
        check(status == 200 and b'HomeSphere' in page and b'/@vite/client' not in page, 'Built frontend served without Vite')
        asset = re.search(rb'(?:src|href)="(/assets/[^\"]+\.js)"', page)
        check(bool(asset), 'Compiled JavaScript asset present')
        status, script, headers = request('GET', asset.group(1).decode())
        check(status == 200 and script and 'javascript' in headers.get('content-type', ''), 'JavaScript content type')
        check('immutable' in headers.get('cache-control', ''), 'Hashed asset caching')
        for path in ('/health', '/db-health', '/openapi.json', '/docs'):
            check(request('GET', path)[0] == 200, path + ' reaches the API')
        check(request('GET', '/files')[0] == 401, 'Anonymous file listing is blocked')
        check(request('GET', '/homes')[0] == 404, 'Retired homes API is unavailable')
        username = args.username or input('Owner username: ').strip()
        password = sys.stdin.readline().rstrip('\r\n') if args.password_stdin else getpass('Owner password: ')
        status, result, headers = request('POST', '/auth/login',
            json.dumps({'username': username, 'password': password}).encode(), {'Content-Type': 'application/json'})
        del password
        check(status == 200, 'Owner login')
        logged_in = True
        check('httponly' in headers.get('set-cookie', '').lower(), 'HttpOnly session cookie')
        check(request('GET', '/auth/me')[0] == 200, 'Current owner session')
        check(request('GET', '/files')[0] == 200, 'Authenticated file listing')
        check(request('GET', '/assets/missing.js')[0] == 404, 'Missing asset response')

        boundary = 'hs' + uuid4().hex
        name = 'login-smoke-' + uuid4().hex[:10] + '.txt'
        content = b'HomeSphere authenticated file verification.\n' * 30000
        body = (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{name}"\r\n'
                'Content-Type: text/plain\r\n\r\n').encode() + content + f'\r\n--{boundary}--\r\n'.encode()
        status, result, _ = request('POST', '/files', body, {'Content-Type': 'multipart/form-data; boundary=' + boundary})
        check(status == 201, 'Authenticated upload larger than 1 MiB')
        record = json.loads(result)
        temporary_ids.append(record['id'])
        check(record['size_bytes'] == len(content) and record['sha256'] == hashlib.sha256(content).hexdigest(), 'Upload metadata and checksum')
        path = '/files/' + record['id']
        status, downloaded, headers = request('GET', path + '/download')
        check(status == 200 and downloaded == content, 'Authenticated download bytes')
        check('attachment' in headers.get('content-disposition', ''), 'Download attachment disposition')
        status, result, _ = request('PATCH', path, json.dumps({'name': 'renamed-' + name}).encode(), {'Content-Type': 'application/json'})
        check(status == 200 and json.loads(result)['name'] == 'renamed-' + name, 'Authenticated rename')
        check(request('PATCH', path, b'{"name":"blocked.txt"}', {'Content-Type': 'application/json', 'Origin': 'https://evil.example'})[0] == 403, 'Cross-origin writes blocked')
        check(request('GET', '/files', headers={'Host': 'evil.example'})[0] == 400, 'Untrusted Host blocked')
        check(request('DELETE', path)[0] == 204, 'Move to recycle bin')
        check(request('GET', path + '/download')[0] == 404, 'Trashed content unavailable')
        check(request('POST', path + '/restore')[0] == 200, 'Restore from recycle bin')
        check(request('GET', path + '/download')[1] == content, 'Restored download bytes')
        check(request('DELETE', path)[0] == 204, 'Move test file back to recycle bin')
        check(request('DELETE', path + '/permanent')[0] == 204, 'Permanently delete only this test file')
        temporary_ids.remove(record['id'])
        check(request('GET', path + '/download')[0] == 404, 'Deleted content unavailable')
        check(request('POST', '/auth/logout')[0] == 204, 'Logout')
        logged_in = False
        check(request('GET', '/files')[0] == 401, 'File access blocked after logout')
        print('All authenticated smoke checks passed at', base)
    finally:
        for file_id in temporary_ids:
            if request('DELETE', '/files/' + file_id)[0] not in {204, 404}:
                print('Could not clean up this script\'s temporary file:', file_id)
            request('DELETE', '/files/' + file_id + '/permanent')
        if logged_in:
            request('POST', '/auth/logout')


if __name__ == '__main__':
    main()
