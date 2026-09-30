"""Install the official native Codex release with GitHub's SHA-256 digest."""
import asyncio
import hashlib
import os
from pathlib import Path
import platform
import re
import tarfile
import tempfile

import httpx

from .providers import ProviderError


def managed_path():
    return Path.home() / 'Library/Application Support/Text Selection Translation Python/bin/codex'


async def install():
    arch = {'arm64': 'aarch64', 'aarch64': 'aarch64', 'x86_64': 'x86_64'}.get(platform.machine())
    if platform.system() != 'Darwin' or not arch:
        raise ProviderError('Automatic Codex installation requires a supported Mac.')
    binary_name = f'codex-{arch}-apple-darwin'
    target = managed_path()
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    async with asyncio.timeout(240):
        async with httpx.AsyncClient(timeout=60, follow_redirects=True) as http:
            response = await http.get('https://api.github.com/repos/openai/codex/releases/latest')
            response.raise_for_status()
            asset = next((a for a in response.json()['assets'] if a['name'] == binary_name + '.tar.gz'), None)
            if not asset or not re.fullmatch(r'sha256:[0-9a-f]{64}', asset.get('digest') or ''):
                raise ProviderError('The official Codex release is missing a download or checksum.')
            url = asset['browser_download_url']
            if not url.startswith('https://github.com/openai/codex/releases/download/'):
                raise ProviderError('Invalid official Codex download URL.')
            with tempfile.TemporaryDirectory(dir=target.parent, prefix='codex-install-') as directory:
                payload = Path(directory) / 'download.tar.gz'
                digest, size = hashlib.sha256(), 0
                async with http.stream('GET', url) as download:
                    download.raise_for_status()
                    with payload.open('wb') as f:
                        async for chunk in download.aiter_bytes():
                            size += len(chunk)
                            if size > 512 * 1024 * 1024:
                                raise ProviderError('Codex download exceeded the size limit.')
                            digest.update(chunk)
                            f.write(chunk)
                if 'sha256:' + digest.hexdigest() != asset['digest']:
                    raise ProviderError('Codex checksum verification failed. Retry installation.')
                binary = Path(directory) / 'codex'
                with tarfile.open(payload, 'r:gz') as archive:
                    member = archive.getmember(binary_name)
                    if not member.isfile() or member.size > 512 * 1024 * 1024:
                        raise ProviderError('Invalid Codex archive.')
                    with archive.extractfile(member) as src, binary.open('wb') as dest:
                        while chunk := src.read(1024 * 1024):
                            dest.write(chunk)
                binary.chmod(0o700)
                os.replace(binary, target)
    return str(target)
