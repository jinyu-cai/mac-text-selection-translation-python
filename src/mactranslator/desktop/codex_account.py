"""ChatGPT browser sign-in and Codex model selection."""
from .antigravity_account import AntigravityAccountWindow


class CodexAccountWindow(AntigravityAccountWindow):
    service = "Codex"
    account = "ChatGPT"
    route = "/codex"
    command = "codex"
    uses_code = False


    def __init__(self, settings):
        from . import widgets as W
        super().__init__(settings)
        self.saved_model = str(settings.fields['model'].stringValue())
        self.saved_effort = str(settings.codex_reasoning.titleOfSelectedItem())
        W.label(self.window.contentView(), 'Reasoning effort', 20, 191, 160)
        self.effort = W.choice(self.window.contentView(), ['auto'], 185, 187, 250)
        W.bind(self.choice, lambda _: self.model_changed(), self.targets)
        self.effort.setEnabled_(False)

    def update(self, data):
        super().update(data)
        if not self.closed and data['status'] == 'ready':
            index = next((i for i, m in enumerate(self.models) if m['id'] == self.saved_model), 0)
            self.choice.selectItemAtIndex_(index)
            self.model_changed()

    def model_changed(self):
        index = self.choice.indexOfSelectedItem()
        if index < 0 or index >= len(self.models):
            return
        model = self.models[index]
        options = ['auto', *model.get('efforts', [])]
        self.effort.removeAllItems()
        self.effort.addItemsWithTitles_(options)
        if model['id'] == self.saved_model and self.saved_effort in options:
            self.effort.selectItemWithTitle_(self.saved_effort)
        self.effort.setEnabled_(True)

    def selection_options(self):
        return {'reasoning': str(self.effort.titleOfSelectedItem())}
