import pytest


class MemoryCredentials:
    def __init__(self):
        self.values = {}

    def get(self, account):
        return self.values.get(account, "")

    def set(self, account, value):
        if value:
            self.values[account] = value
        else:
            self.values.pop(account, None)


@pytest.fixture
def credentials():
    return MemoryCredentials()
