"""Keychain adapter with noninteractive reads; deliberately no legacy fallback."""
from typing import Protocol

from mactranslator import BUNDLE_ID


class CredentialError(RuntimeError):
    pass


class Credentials(Protocol):
    def get(self, account: str) -> str: ...
    def set(self, account: str, value: str) -> None: ...


class KeychainCredentials:
    service = BUNDLE_ID + ".credentials.v1"

    def _query(self, account):
        import Security as S
        return {
            S.kSecClass: S.kSecClassGenericPassword,
            S.kSecAttrService: self.service,
            S.kSecAttrAccount: account,
            S.kSecUseAuthenticationUI: S.kSecUseAuthenticationUIFail,
        }

    @staticmethod
    def _check(status):
        if status:
            raise CredentialError(f"Keychain is unavailable ({status}). Enter the API key again in Settings.")

    def get(self, account):
        import Security as S
        query = self._query(account)
        query[S.kSecReturnData] = True
        query[S.kSecMatchLimit] = S.kSecMatchLimitOne
        status, data = S.SecItemCopyMatching(query, None)
        if status == S.errSecItemNotFound:
            return ""
        self._check(status)
        return bytes(data).decode("utf-8")

    def set(self, account, value):
        import Security as S
        from Foundation import NSData
        query = self._query(account)
        if not value:
            status = S.SecItemDelete(query)
            if status != S.errSecItemNotFound:
                self._check(status)
            return
        encoded = value.encode("utf-8")
        attributes = {S.kSecValueData: NSData.dataWithBytes_length_(encoded, len(encoded))}
        status = S.SecItemUpdate(query, attributes)
        if status == S.errSecItemNotFound:
            query.update(attributes)
            query[S.kSecAttrAccessible] = S.kSecAttrAccessibleAfterFirstUnlock
            status, _ = S.SecItemAdd(query, None)
        self._check(status)
