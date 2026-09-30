"""App-owned login UI; official agy owns OAuth and credential storage."""
import asyncio
import os
import re
import tempfile
from urllib.parse import urlsplit

from .antigravity_cli import executable, stop
from .providers import ProviderError


MODEL_LINE = re.compile(r"^([a-z0-9][a-z0-9._-]+)\t([^\r\n]+)$")
AUTH_URL = re.compile(r'https://accounts\.google\.com/[^\s\x1b<>"\']+')


def login_url(text):
    for match in AUTH_URL.finditer(text):
        value = match.group().rstrip(')')
        parts = urlsplit(value)
        if parts.hostname == 'accounts.google.com' and parts.path in ('/o/oauth2/auth', '/o/oauth2/v2/auth'):
            return value
    return None


class AccountSession:
    def __init__(self):
        self.task = None
        self.process = None
        self.state = {'status': 'idle', 'models': [], 'message': 'Connect your Google account.'}

    def snapshot(self):
        return dict(self.state)

    async def close(self):
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
            self.task = None
        self.state = {'status': 'idle', 'models': [], 'message': 'Login cancelled.'}

    async def start(self, path):
        await self.close()
        # Resolve before starting so missing CLI is reported immediately.
        command, search = executable(path)
        self.state = {'status': 'connecting', 'models': [], 'message': 'Checking Google login…'}
        self.task = asyncio.create_task(self.run(command, search))
        return self.snapshot()

    async def submit_code(self, code):
        if self.state['status'] != 'waiting' or not self.process or self.process.returncode is not None:
            raise ProviderError('The login session has expired. Click Sign in again.')
        code = code.strip()
        if not code or len(code) > 8192 or '\n' in code or '\r' in code:
            raise ProviderError('Enter a valid authorization code.')
        try:
            self.process.stdin.write((code + '\n').encode())
            await self.process.stdin.drain()
        except (BrokenPipeError, ConnectionResetError):
            raise ProviderError('The login session has expired. Click Sign in again.') from None
        self.state.pop('url', None)
        self.state.update(status='connecting', message='Completing sign-in…')
        return self.snapshot()

    async def run(self, command, search):
        env = os.environ.copy()
        env['PATH'] = search
        for key in ('GEMINI_API_KEY', 'GOOGLE_API_KEY', 'GOOGLE_GENAI_USE_VERTEXAI'):
            env.pop(key, None)
        output = bytearray()
        diagnostics = ''
        try:
            with tempfile.TemporaryDirectory(prefix='translator-login-') as directory:
                async with asyncio.timeout(120):
                    self.process = await asyncio.create_subprocess_exec(
                        command, 'models', cwd=directory, env=env, start_new_session=True,
                        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE)

                    async def drain(stream, stdout=False):
                        nonlocal diagnostics
                        while chunk := await stream.read(4096):
                            if stdout:
                                if len(output) + len(chunk) > 1024 * 1024:
                                    raise ProviderError('Unexpected model list size.')
                                output.extend(chunk)
                            # OAuth prompts can appear on either pipe. Never expose raw diagnostics.
                            diagnostics = (diagnostics + chunk.decode(errors='replace'))[-16384:]
                            url = login_url(diagnostics)
                            if url:
                                self.state.update(status='waiting', url=url,
                                                  message='Finish Google sign-in in your browser. Paste the code if requested.')
                                diagnostics = ''

                    await asyncio.gather(drain(self.process.stdout, True), drain(self.process.stderr))
                    code = await self.process.wait()
                    models = []
                    for line in output.decode(errors='replace').splitlines():
                        match = MODEL_LINE.fullmatch(line.strip())
                        if match:
                            models.append({'id': match[1], 'name': match[2]})
                    if code or not models:
                        raise ProviderError('Could not load account models. Retry sign-in; check your connection and account access.')
                    self.state = {'status': 'ready', 'models': models,
                                  'message': 'Connected. Choose a model below.'}
        except asyncio.CancelledError:
            raise
        except TimeoutError:
            self.state = {'status': 'error', 'models': [], 'message': 'Login timed out. Click Sign in to retry.'}
        except Exception:
            self.state = {'status': 'error', 'models': [],
                          'message': 'Could not connect. Check that Antigravity is installed and retry sign-in.'}
        finally:
            if self.process:
                await stop(self.process)
                self.process = None
