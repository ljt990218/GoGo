import asyncio
import hashlib
import io
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import httpx

from app import engine_install as module
from app.config import Settings
from app.engine_install import EngineInstaller, ModelPackage, extract_engine


def model_asset(content):
    return ModelPackage(
        name='kata1-test', url='https://example.invalid/model.bin.gz',
        size=len(content), sha256=hashlib.sha256(content).hexdigest()
    )


class AvailabilityTests(unittest.TestCase):
    def test_clean_supported_platforms_can_download_without_homebrew(self):
        installer = EngineInstaller()
        for target, version in [('macos-arm64', '26.0'), ('macos-x64', '15.0'), ('windows-x64', '')]:
            installer.platform = target
            with self.subTest(platform=target), patch.object(installer, 'local_engine', return_value=None), patch.object(module.platform, 'mac_ver', return_value=(version, (), '')):
                status = installer.status(Settings())
                self.assertTrue(all(option['available'] for option in status['options']))

    def test_old_mac_gets_specific_minimum_version_and_can_use_existing_engine(self):
        installer = EngineInstaller()
        installer.platform = 'macos-arm64'
        with patch.object(installer, 'local_engine', return_value=None), patch.object(module.platform, 'mac_ver', return_value=('15.0', (), '')):
            self.assertIn('macOS 26.0', installer.unavailable('light', Settings()))
        with patch.object(installer, 'local_engine', return_value=Path('/existing/katago')):
            self.assertEqual(installer.unavailable('light', Settings()), '')

    def test_zip_rejects_escaping_and_link_entries_without_destroying_existing_engine(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            destination = root / 'installed'
            destination.mkdir()
            existing = destination / 'katago.exe'
            existing.write_bytes(b'existing engine')
            for name in ['../outside', '/outside', 'C:/outside', 'folder\\outside', 'symlink']:
                with self.subTest(name=name):
                    archive = root / 'package.zip'
                    with zipfile.ZipFile(archive, 'w') as bundle:
                        entry = zipfile.ZipInfo(name)
                        if name == 'symlink':
                            entry.external_attr = 0o120777 << 16
                        bundle.writestr(entry, 'outside')
                    with self.assertRaises(ValueError):
                        extract_engine(archive, destination, 'katago.exe')
                    self.assertEqual(existing.read_bytes(), b'existing engine')
                    self.assertFalse((root / 'outside').exists())

    def test_system_proxy_is_used_when_only_local_bypass_rules_exist(self):
        output = subprocess.CompletedProcess([], 0, stdout='HTTPSEnable : 1\nHTTPSProxy : 127.0.0.1\nHTTPSPort : 7890\n')
        with patch.object(module.platform, 'system', return_value='Darwin'), patch.object(module, 'getproxies', return_value={'no': 'localhost,127.0.0.1'}), patch.object(module.subprocess, 'run', return_value=output), patch.object(module.httpx, 'AsyncHTTPTransport') as transport:
            mounts = module.download_mounts()
            self.assertIn('https://', mounts)
            transport.assert_called_once_with(proxy='http://127.0.0.1:7890')

    def test_explicit_proxy_and_bypass_all_are_respected(self):
        for proxies in [{'https': 'http://example.invalid:8080'}, {'no': '*'}]:
            with self.subTest(proxies=proxies), patch.object(module.platform, 'system', return_value='Darwin'), patch.object(module, 'getproxies', return_value=proxies), patch.object(module.subprocess, 'run') as command:
                self.assertEqual(module.download_mounts(), {})
                command.assert_not_called()


class DownloadTests(unittest.IsolatedAsyncioTestCase):
    async def test_verified_cache_works_without_any_network_request(self):
        content = b'verified model'
        asset = model_asset(content)
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / 'model.bin.gz'
            target.write_bytes(content)
            def unexpected_request(request):
                self.fail('有效缓存不应请求网络')
            async with httpx.AsyncClient(transport=httpx.MockTransport(unexpected_request)) as client:
                installer = EngineInstaller()
                await installer.download(client, asset, target)
            self.assertEqual(target.read_bytes(), content)
            self.assertEqual(installer.downloaded, len(content))

    async def test_failed_checksum_preserves_previous_file_then_retry_succeeds(self):
        content = b'new verified model'
        asset = model_asset(content)
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / 'model.bin.gz'
            target.write_bytes(b'previous model')
            installer = EngineInstaller()
            async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, content=b'x' * len(content)))) as client:
                with self.assertRaises(ValueError):
                    await installer.download(client, asset, target)
            self.assertEqual(target.read_bytes(), b'previous model')
            self.assertFalse(target.with_suffix('.gz.part').exists())
            async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, content=content))) as client:
                await installer.download(client, asset, target)
            self.assertEqual(target.read_bytes(), content)

    async def test_failed_install_does_not_configure_and_releases_lock(self):
        installer = EngineInstaller()
        installer.platform = 'windows-x64'
        zip_data = io.BytesIO()
        with zipfile.ZipFile(zip_data, 'w') as bundle:
            bundle.writestr('katago.exe', b'fixture executable')
        package = zip_data.getvalue()
        engine = installer.manifest.engines['windows-x64']
        engine.url = 'https://example.invalid/engine.zip'
        engine.size = len(package)
        engine.sha256 = hashlib.sha256(package).hexdigest()
        installer.manifest.models['light'] = model_asset(b'expected model')
        configured = []
        async def configure(binary, weights):
            configured.append((binary, weights))
        def respond(request):
            return httpx.Response(200, content=package if request.url.path.endswith('.zip') else b'invalid model!')
        lock = asyncio.Lock()
        await lock.acquire()
        with tempfile.TemporaryDirectory() as folder, patch.object(module, 'DATA', Path(folder)):
            client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
            with patch.object(module.httpx, 'AsyncClient', return_value=client), patch.object(module, 'download_mounts', return_value={}):
                await installer.run('light', lock, configure, None, [])
        self.assertEqual(installer.state, 'failed')
        self.assertEqual(configured, [])
        self.assertFalse(lock.locked())

    async def test_duplicate_install_is_rejected_while_operation_is_running(self):
        installer = EngineInstaller()
        installer.platform = 'windows-x64'
        lock = asyncio.Lock()
        await lock.acquire()
        with patch.object(installer, 'local_engine', return_value=None):
            with self.assertRaises(module.AppError) as error:
                await installer.start('light', lock, None, Settings())
        self.assertEqual(error.exception.code, 'ENGINE_BUSY')
        self.assertIsNone(installer.task)
        lock.release()


if __name__ == '__main__':
    unittest.main()
