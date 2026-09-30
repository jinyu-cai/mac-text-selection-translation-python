"""Download the official native CLI, verify its manifest hash, install atomically."""
import asyncio
import hashlib
import os
from pathlib import Path
import platform
import tarfile
import tempfile
from urllib.parse import urlsplit

import httpx

from .providers import ProviderError

BASE = 'https://antigravity-cli-auto-updater-974169037036.us-central1.run.app'


def managed_path():
    return Path.home() / 'Library/Application Support/Text Selection Translation Python/bin/agy'


async def install():
    arch = {'arm64': 'arm64', 'aarch64': 'arm64', 'x86_64': 'amd64'}.get(platform.machine())
    if platform.system() != 'Darwin' or not arch:
        raise ProviderError('Automatic Antigravity installation requires a supported Mac.')
    target = managed_path()
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    async with asyncio.timeout(160):
        async with httpx.AsyncClient(timeout=60, follow_redirects=True) as http:
            response = await http.get(f'{BASE}/manifests/darwin_{arch}.json')
            response.raise_for_status()
            manifest = response.json()
            url, expected = manifest['url'], manifest['sha512']
            parsed = urlsplit(url)
            if parsed.scheme != 'https' or parsed.username or parsed.password:
                raise ProviderError('Invalid official download URL.')
            if not isinstance(expected, str) or len(expected) != 128:
                raise ProviderError('Invalid official download checksum.')
            with tempfile.TemporaryDirectory(dir=target.parent, prefix='install-') as directory:
                payload = Path(directory) / 'download'
                digest = hashlib.sha512()
                size = 0
                async with http.stream('GET', url) as download:
                    download.raise_for_status()
                    with payload.open('wb') as f:
                        async for chunk in download.aiter_bytes():
                            size += len(chunk)
                            if size > 512 * 1024 * 1024:
                                raise ProviderError('Antigravity download exceeded the size limit.')
                            digest.update(chunk)
                            f.write(chunk)
                if digest.hexdigest() != expected.lower():
                    raise ProviderError('Antigravity checksum verification failed. Retry installation.')
                binary = Path(directory) / 'agy'
                if '.tar.gz' in parsed.path:
                    with tarfile.open(payload, 'r:gz') as archive:
                        member = archive.getmember('antigravity')
                        if not member.isfile() or member.size > 512 * 1024 * 1024:
                            raise ProviderError('Invalid Antigravity archive.')
                        with archive.extractfile(member) as src, binary.open('wb') as dest:
                            while chunk := src.read(1024 * 1024):
                                dest.write(chunk)
                else:
                    payload.rename(binary)
                binary.chmod(0o700)
                os.replace(binary, target)
    return str(target)
