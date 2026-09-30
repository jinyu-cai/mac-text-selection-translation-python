"""Codex owns browser OAuth, token storage and refresh; the app displays status."""
import asyncio
import tempfile
from urllib.parse import urlsplit

from .codex_cli import Client, executable
from mactranslator.codex_models import list_models
from .providers import ProviderError


def valid_login_url(value):
    p = urlsplit(value)
    return p.scheme == 'https' and p.hostname in ('auth.openai.com', 'chatgpt.com') and not p.username and not p.password and p.port in (None, 443)


class AccountSession:
    def __init__(self):
        self.task = None
        self.state = {'status': 'idle', 'models': [], 'message': 'Connect your ChatGPT account.'}

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
        executable(path)
        self.state = {'status': 'connecting', 'models': [], 'message': 'Checking ChatGPT login…'}
        self.task = asyncio.create_task(self.run(path))
        return self.snapshot()

    async def run(self, path):
        try:
            async with asyncio.timeout(300):
                with tempfile.TemporaryDirectory(prefix='translator-codex-login-') as directory:
                    async with Client(path, directory) as client:
                        login_id = None
                        try:
                            account = (await client.call('account/read')).get('account')
                            if not account or account.get('type') not in ('chatgpt', 'chatgptAuthTokens'):
                                login = await client.call('account/login/start', {'type': 'chatgpt'})
                                login_id = login['loginId']
                                if not valid_login_url(login['authUrl']):
                                    raise ProviderError('Unexpected Codex login URL.')
                                self.state.update(status='waiting', url=login['authUrl'],
                                                  message='Finish ChatGPT sign-in in your browser. This window updates automatically.')
                                while True:
                                    event = await client.events.get()
                                    if event['method'] == 'disconnected':
                                        raise ProviderError('Codex disconnected. Retry sign-in.')
                                    data = event.get('params', {})
                                    if event['method'] == 'account/login/completed' and data.get('loginId') == login_id:
                                        if not data.get('success'):
                                            raise ProviderError('ChatGPT sign-in failed. Please retry.')
                                        login_id = None
                                        break
                            models = await list_models(client)
                            if not models:
                                raise ProviderError('No Codex models are available for this account.')
                            self.state = {'status': 'ready', 'models': models,
                                          'message': 'Connected to ChatGPT. Choose a model below.'}
                        finally:
                            if login_id:
                                try:
                                    await asyncio.wait_for(client.call('account/login/cancel', {'loginId': login_id}), 3)
                                except Exception:
                                    pass
        except asyncio.CancelledError:
            raise
        except TimeoutError:
            self.state = {'status': 'error', 'models': [], 'message': 'Sign-in timed out. Click Sign in to retry.'}
        except Exception:
            self.state = {'status': 'error', 'models': [],
                          'message': 'Could not connect to Codex. Check installation, connection and account access.'}
