import asyncio
import sys

import pytest

from mactranslator.backend.antigravity_account import AccountSession, login_url
from mactranslator.backend.providers import ProviderError


def fake(tmp_path, source):
    p = tmp_path / 'agy'
    p.write_text(f'#!{sys.executable}\nimport sys,time\n' + source)
    p.chmod(0o700)
    return str(p)


async def wait_for(session, status):
    async with asyncio.timeout(4):
        while session.state['status'] != status:
            await asyncio.sleep(.01)


def test_only_google_oauth_links():
    assert login_url('https://evil.test/oauth') is None
    assert login_url('https://accounts.google.com.evil.test/o/oauth2/auth') is None
    assert login_url('https://accounts.google.com/other') is None
    assert login_url('Login: https://accounts.google.com/o/oauth2/auth?state=abc\n')


async def test_browser_code_flow(tmp_path):
    path = fake(tmp_path, '''
assert sys.argv[1:] == ['models']
sys.stderr.write('Authentication required. https://accounts.google.com/o/oauth2/auth?state=test\\n')
sys.stderr.flush()
assert sys.stdin.readline().strip() == 'test-code'
print('gemini-test-medium\\tGemini Test (Medium)')
''')
    s = AccountSession()
    try:
        await s.start(path)
        await wait_for(s, 'waiting')
        assert s.snapshot()['url'].startswith('https://accounts.google.com/')
        await s.submit_code('test-code')
        await wait_for(s, 'ready')
        assert s.state['models'] == [{'id':'gemini-test-medium','name':'Gemini Test (Medium)'}]
        assert 'url' not in s.state
        assert 'test-code' not in str(s.state)
    finally:
        await s.close()


async def test_existing_login_and_cancel(tmp_path):
    s = AccountSession()
    await s.start(fake(tmp_path, "print('gemini-test\\tGemini Test')"))
    await wait_for(s, 'ready')
    await s.start(fake(tmp_path, 'time.sleep(60)'))
    async with asyncio.timeout(3):
        while s.process is None:
            await asyncio.sleep(.01)
    proc = s.process
    await s.close()
    assert proc.returncode is not None
    assert s.state['status'] == 'idle'
    with pytest.raises(ProviderError):
        await s.submit_code('expired')


async def test_no_raw_error_exposure(tmp_path):
    s = AccountSession()
    try:
        await s.start(fake(tmp_path, "sys.stderr.write('PRIVATE TOKEN'); sys.exit(1)"))
        await wait_for(s, 'error')
        assert 'PRIVATE' not in str(s.state)
    finally:
        await s.close()
