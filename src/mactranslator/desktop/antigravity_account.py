"""Native account onboarding without opening Terminal."""
import AppKit as A
from Foundation import NSURL, NSObject
from PyObjCTools import AppHelper

from . import widgets as W


class AccountWindowDelegate(NSObject):
    def windowShouldClose_(self, sender):
        self.owner.close()
        return False


class AntigravityAccountWindow:
    service = "Antigravity"
    account = "Google"
    route = "/antigravity"
    command = "agy"
    uses_code = True

    def __init__(self, settings):
        self.settings, self.app = settings, settings.app
        self.provider_id = settings.draft['providers'][settings.index]['id']
        self.cli_path = str(settings.fields['cli_path'].stringValue()).strip() or self.command
        self.targets, self.models = [], []
        self.closed = False
        self.opened_url = None
        self.window = W.window(self.service + ' Account', 640, 380)
        self.delegate = AccountWindowDelegate.alloc().init()
        self.delegate.owner = self
        self.window.setDelegate_(self.delegate)
        root = self.window.contentView()
        W.label(root, f'Connect your {self.account} account', 20, 330, 600, 26)
        W.label(root, 'Sign-in opens in your browser. No Terminal commands are needed.', 20, 297, 600)
        self.login = W.button(root, 'Sign in / Refresh Models', 20, 251, 230, lambda _: self.start(), self.targets)
        W.button(root, 'Install ' + self.service, 270, 251, 170, lambda _: self.install(), self.targets)
        self.status = W.label(root, 'Click Sign in to connect or reuse your existing login.', 20, 199, 600, 44)
        code_label = W.label(root, 'Authorization code (only if Google provides one)', 20, 171, 600)
        code_label.setHidden_(not self.uses_code)
        self.code = W.field(root, 20, 136, 435, secure=True)
        self.submit = W.button(root, 'Submit Code', 470, 134, 150, lambda _: self.send_code(), self.targets)
        self.submit.setEnabled_(False)
        self.code.setHidden_(not self.uses_code)
        self.submit.setHidden_(not self.uses_code)
        if not self.uses_code:
            W.label(root, "Login is saved by Codex. Account usage limits apply.", 20, 145, 600)
        self.choice = W.choice(root, ['Sign in to load models'], 20, 88, 600)
        self.use = W.button(root, 'Use Selected Model', 400, 25, 220, lambda _: self.apply(), self.targets)
        self.use.setEnabled_(False)
        W.button(root, 'Close', 20, 25, 100, lambda _: self.close(), self.targets)

    def show(self):
        self.window.makeKeyAndOrderFront_(None)
        A.NSApp.activateIgnoringOtherApps_(True)

    def failure(self, error):
        if self.closed:
            return
        self.status.setStringValue_(str(error))
        self.login.setEnabled_(True)

    def install(self):
        self.login.setEnabled_(False)
        self.status.setStringValue_(f'Downloading and verifying the official {self.service} CLI…')
        self.app.request('POST', self.route + '/install', done=self.installed, error=self.failure, timeout=260)

    def installed(self, data):
        if self.closed:
            return
        self.cli_path = data['cli_path']
        self.login.setEnabled_(True)
        self.status.setStringValue_(f'Installed. Click Sign in to connect your {self.account} account.')

    def start(self):
        self.login.setEnabled_(False)
        self.opened_url = None
        self.models = []
        self.use.setEnabled_(False)
        self.status.setStringValue_('Checking login…')
        self.app.request('POST', self.route + '/login', json={'cli_path': self.cli_path},
                         done=self.update, error=self.failure)

    def update(self, data):
        if self.closed:
            return
        status = data['status']
        self.status.setStringValue_(data['message'])
        self.submit.setEnabled_(status == 'waiting')
        url = data.get('url')
        if url and url != self.opened_url:
            self.opened_url = url
            A.NSWorkspace.sharedWorkspace().openURL_(NSURL.URLWithString_(url))
        if status == 'ready':
            self.models = data['models']
            self.choice.removeAllItems()
            self.choice.addItemsWithTitles_([m['name'] + ' — ' + m['id'] for m in self.models])
            self.use.setEnabled_(bool(self.models))
        if status in ('connecting', 'waiting'):
            AppHelper.callLater(1, self.poll)
        else:
            self.login.setEnabled_(True)

    def poll(self):
        if not self.closed:
            self.app.request('GET', self.route + '/login', done=self.update, error=self.failure)

    def send_code(self):
        code = str(self.code.stringValue()).strip()
        self.code.setStringValue_('')
        self.submit.setEnabled_(False)
        self.app.request('POST', self.route + '/login/code', json={'code': code},
                         done=lambda _: None, error=self.failure)

    def selection_options(self):
        return {}

    def apply(self):
        index = self.choice.indexOfSelectedItem()
        if index < 0 or index >= len(self.models):
            return
        settings = self.settings
        settings.collect_provider()
        for i, p in enumerate(settings.draft['providers']):
            if p['id'] == self.provider_id:
                p.update(model=self.models[index]['id'], cli_path=self.cli_path, **self.selection_options())
                settings.refresh_list(i)
                settings.save()
                self.close()
                return
        self.status.setStringValue_('This service was removed. Close and add it again.')

    def close(self):
        if self.closed:
            return
        self.closed = True
        self.code.setStringValue_('')
        self.app.request('DELETE', self.route + '/login', error=lambda _: None)
        self.window.orderOut_(None)
