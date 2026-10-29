#!/usr/bin/env python3
"""Restore a HomeSphere backup into a new isolated local test stack."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import socket
import subprocess
import tarfile
import tempfile
from urllib.parse import unquote, urlsplit
from urllib.request import urlopen
from uuid import uuid4


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('backup', type=Path)
    parser.add_argument('--port', type=int, default=18081)
    parser.add_argument('--plan', action='store_true', help='Validate only; start no containers')
    args = parser.parse_args()
    backup = args.backup.expanduser().resolve(strict=True)
    for filename in ('database.dump', 'uploads.tar.gz', '.env'):
        if not (backup / filename).is_file():
            raise RuntimeError('Backup is missing ' + filename)
    if not 1024 <= args.port <= 65535 or args.port in {8001, 8080, 5173}:
        raise RuntimeError('Choose a separate local port, such as 18081.')
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', args.port))

    archived = {}
    with tarfile.open(backup / 'uploads.tar.gz', 'r:gz') as archive:
        seen = set()
        for member in archive:
            if member.name in seen:
                raise RuntimeError('Duplicate archive entry')
            seen.add(member.name)
            if member.isdir() and member.name.rstrip('/') == 'uploads':
                continue
            if not member.isfile() or not re.fullmatch(r'uploads/(?:[a-f0-9]{32}|\.lock)', member.name):
                raise RuntimeError('Unexpected archive entry; refusing extraction')
            if member.name == 'uploads/.lock':
                continue
            digest = hashlib.sha256()
            size = 0
            with archive.extractfile(member) as payload:
                for chunk in iter(lambda: payload.read(1024 * 1024), b''):
                    digest.update(chunk)
                    size += len(chunk)
            archived[member.name.split('/')[1]] = (size, digest.hexdigest())

    project = 'homesphere-restore-' + uuid4().hex[:12]
    folder = Path(tempfile.mkdtemp(prefix=project + '-'))
    env = str(backup / '.env')
    config = {
        'services': {
            'db': {
                'image': 'postgres:17', 'env_file': [env],
                'environment': {'POSTGRES_USER': 'homesphere', 'POSTGRES_DB': 'homesphere'},
                'volumes': ['restore_db:/var/lib/postgresql/data'],
                'healthcheck': {'test': ['CMD-SHELL', 'pg_isready -U homesphere -d homesphere'],
                                'interval': '2s', 'timeout': '3s', 'retries': 30},
            },
            'api': {
                'image': 'homesphere-api', 'env_file': [env],
                'environment': {'UPLOAD_DIR': '/data/uploads'},
                'volumes': ['restore_uploads:/data/uploads'],
                'depends_on': {'db': {'condition': 'service_healthy'}},
                'healthcheck': {
                    'test': ['CMD', 'python', '-c', "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/db-health', timeout=2).read()"],
                    'interval': '2s', 'timeout': '3s', 'start_period': '5s', 'retries': 30,
                },
            },
            'web': {
                'image': 'homesphere-web',
                'environment': {'MAX_FILE_SIZE_BYTES': '${MAX_FILE_SIZE_BYTES:-26214400}'},
                'ports': [f'127.0.0.1:{args.port}:8080'],
                'depends_on': {'api': {'condition': 'service_healthy'}},
                'healthcheck': {'test': ['CMD', 'wget', '-q', '--spider', 'http://127.0.0.1:8080/web-health'],
                                'interval': '2s', 'timeout': '3s', 'retries': 30},
            },
        },
        'volumes': {'restore_db': {}, 'restore_uploads': {}},
    }
    config_file = folder / 'compose.json'
    config_file.write_text(json.dumps(config, indent=2))
    command = ['docker', 'compose', '-p', project, '--env-file', env, '-f', str(config_file)]

    def run(*arguments, stdin=None):
        return subprocess.run(command + list(arguments), stdin=stdin, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, check=True)

    resolved = json.loads(run('config', '--format', 'json').stdout)
    api_environment = resolved['services']['api']['environment']
    db_environment = resolved['services']['db']['environment']
    database = urlsplit(api_environment.get('DATABASE_URL', ''))
    if (database.hostname != 'db' or database.port not in (None, 5432)
            or database.path != '/homesphere' or database.username != 'homesphere'
            or not db_environment.get('POSTGRES_PASSWORD')
            or unquote(database.password or '') != db_environment['POSTGRES_PASSWORD']):
        raise RuntimeError('Backup database settings must target the isolated db service and use matching credentials.')
    for volume in resolved['volumes'].values():
        if volume.get('external') or not volume.get('name', '').startswith(project + '_'):
            raise RuntimeError('Refusing a volume outside this new restore project')

    cleanup = folder / 'cleanup.sh'
    cleanup.write_text('#!/bin/sh\nset -eu\n' + shlex.join(command + ['down', '--volumes']) + '\n')
    print('Restore project:', project, flush=True)
    print('To remove only this test copy afterward: bash ' + shlex.quote(str(cleanup)), flush=True)
    if args.plan:
        print(f'Validation passed: {len(archived)} archived file(s); no containers started.')
        return

    print('1/5 Starting a new empty test database...', flush=True)
    run('up', '-d', '--no-build', '--wait', '--wait-timeout', '90', 'db')
    print('2/5 Restoring the database backup...', flush=True)
    with (backup / 'database.dump').open('rb') as dump:
        run('exec', '-T', 'db', 'pg_restore', '--exit-on-error', '--no-owner', '--no-privileges',
            '-U', 'homesphere', '-d', 'homesphere', stdin=dump)
    sql = "SELECT json_build_object('files', COALESCE((SELECT json_agg(row_to_json(f)) FROM (SELECT id, name, size_bytes, sha256, storage_key, state FROM files ORDER BY id) f), '[]'::json), 'homes', (SELECT count(*) FROM homes));"
    metadata = json.loads(run('exec', '-T', 'db', 'psql', '-X', '-v', 'ON_ERROR_STOP=1',
                             '-U', 'homesphere', '-d', 'homesphere', '-At', '-c', sql).stdout)
    records = metadata['files']
    if any(row['state'] != 'ready' for row in records):
        raise RuntimeError('Backup contains unfinished file operations; review it before continuing.')
    expected = {row['storage_key']: (row['size_bytes'], row['sha256']) for row in records}
    if archived != expected:
        raise RuntimeError('Database metadata and archived file contents do not match.')
    print('3/5 Restoring uploads into a new test volume...', flush=True)
    with (backup / 'uploads.tar.gz').open('rb') as archive:
        run('run', '--rm', '--no-deps', '-T', '--entrypoint', 'tar', 'api',
            '-xzf', '-', '-C', '/data/uploads', '--strip-components=1', '--no-same-owner', stdin=archive)
    print('Checking restored upload volume checksums...', flush=True)
    verification = """import hashlib, json
from pathlib import Path
records = json.loads(RECORDS_PLACEHOLDER)
for row in records:
    digest = hashlib.sha256()
    size = 0
    with (Path('/data/uploads') / row['storage_key']).open('rb') as payload:
        for chunk in iter(lambda: payload.read(1024 * 1024), b''):
            digest.update(chunk)
            size += len(chunk)
    assert (size, digest.hexdigest()) == (row['size_bytes'], row['sha256']), 'Restored bytes differ'
""".replace('RECORDS_PLACEHOLDER', repr(json.dumps(records)))
    run('run', '--rm', '--no-deps', '-T', 'api', 'python', '-c', verification)
    # Older backups predate owner tables. Apply only the current additive migrations
    # in this isolated project before starting its copy of the new application.
    run('run', '--rm', '--no-deps', '-T', 'api', 'alembic', 'upgrade', 'head')
    owner_count = int(run('exec', '-T', 'db', 'psql', '-X', '-v', 'ON_ERROR_STOP=1',
                         '-U', 'homesphere', '-d', 'homesphere', '-At',
                         '-c', 'SELECT count(*) FROM owners').stdout)
    print('4/5 Starting the restored application...', flush=True)
    run('up', '-d', '--no-build', '--wait', '--wait-timeout', '90')
    base = f'http://localhost:{args.port}'
    print('5/5 Checking the restored frontend and login protection...', flush=True)
    with urlopen(base + '/', timeout=15) as response:
        if response.status != 200 or b'HomeSphere' not in response.read():
            raise RuntimeError('Restored frontend did not load.')
    from urllib.error import HTTPError
    try:
        urlopen(base + '/files', timeout=15)
        raise RuntimeError('Restored files are accessible without signing in.')
    except HTTPError as failure:
        if failure.code != 401:
            raise
    if not owner_count:
        print('This older backup contains no owner account. Create one in this TEST copy:')
        print(shlex.join(command + ['run', '--rm', '--no-deps', 'api', 'python', '-m', 'app.create_owner']))
    else:
        print('Sign in to the restored copy using the credentials saved in the backup.')
    print(f'RESTORE VERIFIED: {len(records)} file(s), {metadata["homes"]} legacy homes row(s).')
    print('Open the restored test copy:', base)
    print('The main HomeSphere containers and volumes were not modified.')


if __name__ == '__main__':
    try:
        main()
    except subprocess.CalledProcessError as exc:
        print('Restore test stopped. Docker reported:')
        print(exc.stderr.decode(errors='replace').strip())
        raise SystemExit(1)
    except (OSError, RuntimeError, ValueError, tarfile.TarError) as exc:
        print('Restore test stopped:', exc)
        raise SystemExit(1)
