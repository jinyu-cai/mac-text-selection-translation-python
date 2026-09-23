import httpx

from mactranslator.desktop.runtime import BackendRuntime


def test_runtime_ephemeral_loopback_and_clean_shutdown(tmp_path, credentials):
    runtime = BackendRuntime(tmp_path / "runtime.sqlite3", credentials)
    try:
        assert runtime.start().result(timeout=10)["ready"]
        assert runtime.base_url.startswith("http://127.0.0.1:")
        response = httpx.get(runtime.base_url + "/api/v1/health", trust_env=False)
        assert response.status_code == 401
        result = runtime.submit(runtime.request("GET", "/settings")).result(timeout=5)
        assert result["providers"] == []
    finally:
        runtime.stop()
    assert not runtime.thread.is_alive()
