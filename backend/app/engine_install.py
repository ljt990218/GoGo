import asyncio
import hashlib
import os
import platform
import re
import shutil
import stat
import subprocess
import tempfile
import zipfile
from dataclasses import replace
from pathlib import Path, PurePosixPath
from typing import Annotated, Literal
from urllib.parse import urlparse
from urllib.request import getproxies

import httpx
from pydantic import Field, StrictInt, field_validator, model_validator
from starlette.concurrency import run_in_threadpool

from .config import ROOT, Settings
from .errors import AppError
from .models import Contract

Tier = Literal['light', 'balanced', 'advanced']
Platform = Literal['macos-arm64', 'macos-x64', 'windows-x64']
DATA = ROOT / '.gogo'
TIER_TEXT = {
    'light': ('轻量版', '优先照顾低配置电脑，速度较快；模型较旧，分析能力有限。'),
    'balanced': ('均衡版', '适合日常复盘，计算负担更大。'),
    'advanced': ('高阶版', '供性能较好的电脑选择，计算和内存开销更大。')
}


class Download(Contract):
    url: str | None
    size: Annotated[StrictInt, Field(gt=0)] | None
    sha256: Annotated[str, Field(pattern='^[a-f0-9]{64}$')] | None


class EnginePackage(Download):
    format: Literal['zip', 'dmg']
    bundle: Literal['KaTrain.app'] | None
    minimumMacOS: Annotated[str, Field(pattern=r'^\d+\.\d+$')] | None
    executable: str

    @field_validator('executable')
    @classmethod
    def relative_executable(cls, value):
        path = PurePosixPath(value)
        if not value or path.is_absolute() or '..' in path.parts or '\\' in value or ':' in value:
            raise ValueError('引擎入口必须是安全的包内相对路径')
        return value

    @model_validator(mode='after')
    def package_layout(self):
        if self.format == 'dmg' and (
            not self.bundle or not self.minimumMacOS
            or not self.executable.startswith(self.bundle + '/')
        ):
            raise ValueError('DMG 必须明确应用包、最低系统版本与包内入口')
        if self.format == 'zip' and (self.bundle is not None or self.minimumMacOS is not None):
            raise ValueError('ZIP 不使用 Mac 应用包字段')
        return self


class ModelPackage(Download):
    name: Annotated[str, Field(pattern='^kata1-[a-zA-Z0-9-]+$')]


class DownloadManifest(Contract):
    engineVersion: Literal['1.18.1']
    engines: dict[Platform, EnginePackage]
    models: dict[Tier, ModelPackage]


class InstallRequest(Contract):
    tier: Tier


class EmptyRequest(Contract):
    pass


def current_platform():
    system = platform.system()
    machine = platform.machine().lower()
    if system == 'Darwin':
        if machine == 'arm64':
            return 'macos-arm64'
        if machine == 'x86_64':
            return 'macos-x64'
    if system == 'Windows' and machine in ('amd64', 'x86_64'):
        return 'windows-x64'
    return 'unsupported'


def ready(asset):
    if asset is None or not asset.url or not asset.size or not asset.sha256:
        return False
    parsed = urlparse(asset.url)
    return parsed.scheme == 'https' and bool(parsed.hostname) and not (
        parsed.username or parsed.password or parsed.fragment
    )


def verified(path, asset):
    if not path.is_file() or path.stat().st_size != asset.size:
        return False
    with path.open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest() == asset.sha256


def executable_file(path):
    return path.is_absolute() and path.is_file() and os.access(path, os.X_OK)


def download_mounts():
    proxies = getproxies()
    if (
        platform.system() != 'Darwin' or proxies.get('https') or proxies.get('all')
        or '*' in [host.strip() for host in proxies.get('no', '').split(',')]
    ):
        return {}
    try:
        output = subprocess.run(
            ['/usr/sbin/scutil', '--proxy'], capture_output=True, text=True, check=True, timeout=3
        ).stdout
        values = dict(re.findall(r'^\s*(HTTPSEnable|HTTPSProxy|HTTPSPort)\s*:\s*(.*?)\s*$', output, re.MULTILINE))
        if values.get('HTTPSEnable') != '1' or not values.get('HTTPSProxy') or not values.get('HTTPSPort'):
            return {}
        host = values['HTTPSProxy']
        port = int(values['HTTPSPort'])
        if not 1 <= port <= 65535 or any(character in host for character in '/@ \t\n'):
            return {}
        if ':' in host and not host.startswith('['):
            host = f'[{host}]'
        return {'https://': httpx.AsyncHTTPTransport(proxy=f'http://{host}:{port}')}
    except (OSError, ValueError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return {}


def reuse_model(candidates, target, asset):
    if verified(target, asset):
        return True
    partial = target.with_suffix(target.suffix + '.part')
    for source in candidates:
        if source == target:
            continue
        try:
            valid = verified(source, asset)
        except OSError:
            continue
        if not valid:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copyfile(source, partial)
            if not verified(partial, asset):
                raise ValueError('本机模型复制后校验失败')
            os.replace(partial, target)
            return True
        finally:
            partial.unlink(missing_ok=True)
    return False


class EngineInstallError(Exception):
    pass


def replace_directory(source, destination):
    previous = None
    if destination.exists():
        previous = Path(tempfile.mkdtemp(prefix='.previous-', dir=destination.parent))
        previous.rmdir()
        os.replace(destination, previous)
    try:
        os.replace(source, destination)
    except OSError:
        if previous:
            os.replace(previous, destination)
        raise
    else:
        if previous:
            shutil.rmtree(previous)


def extract_engine(archive, destination, executable):
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix='.extract-', dir=destination.parent))
    try:
        with zipfile.ZipFile(archive) as bundle:
            entries = bundle.infolist()
            if len(entries) > 4096 or sum(entry.file_size for entry in entries) > 2 * 1024 ** 3:
                raise ValueError('引擎安装包解压后过大')
            for entry in entries:
                relative = PurePosixPath(entry.filename)
                mode = entry.external_attr >> 16
                if (
                    relative.is_absolute() or '..' in relative.parts
                    or '\\' in entry.filename or ':' in entry.filename
                    or stat.S_ISLNK(mode)
                    or (stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR))
                ):
                    raise ValueError('引擎安装包包含不安全路径')
                target = temporary.joinpath(*relative.parts)
                if entry.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with bundle.open(entry) as source, target.open('wb') as output:
                        shutil.copyfileobj(source, output)
            binary = temporary / executable
            if not binary.is_file():
                raise ValueError('安装包缺少约定的引擎程序')
            if os.name != 'nt':
                binary.chmod(0o755)
        replace_directory(temporary, destination)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)


def extract_mac_engine(archive, destination, package):
    destination.parent.mkdir(parents=True, exist_ok=True)
    mount = Path(tempfile.mkdtemp(prefix='.mount-', dir=destination.parent))
    try:
        with tempfile.TemporaryDirectory(prefix='.extract-', dir=destination.parent) as directory:
            temporary = Path(directory)
            subprocess.run(
                ['/usr/bin/hdiutil', 'attach', '-readonly', '-nobrowse', '-mountpoint', str(mount), str(archive)],
                stdin=subprocess.DEVNULL, capture_output=True, check=True, timeout=120
            )
            source = mount / package.bundle
            if not source.is_dir() or source.is_symlink():
                raise EngineInstallError('下载包中缺少约定的 Mac 引擎应用包')
            subprocess.run(
                ['/usr/bin/ditto', str(source), str(temporary / package.bundle)],
                stdin=subprocess.DEVNULL, capture_output=True, check=True, timeout=180
            )
            subprocess.run(
                ['/usr/bin/codesign', '--verify', '--deep', '--strict', str(temporary / package.bundle)],
                stdin=subprocess.DEVNULL, capture_output=True, check=True, timeout=60
            )
            binary = temporary / package.executable
            if not executable_file(binary):
                raise EngineInstallError('下载包中缺少可执行的 KataGo 引擎')
            replace_directory(temporary, destination)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        raise EngineInstallError('Mac 安装包挂载、复制或签名校验未完成，请重试') from None
    finally:
        if os.path.ismount(mount):
            try:
                detached = subprocess.run(
                    ['/usr/bin/hdiutil', 'detach', str(mount)],
                    stdin=subprocess.DEVNULL, capture_output=True, timeout=30
                )
                if detached.returncode != 0:
                    subprocess.run(
                        ['/usr/bin/hdiutil', 'detach', '-force', str(mount)],
                        stdin=subprocess.DEVNULL, capture_output=True, check=True, timeout=30
                    )
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
                raise EngineInstallError('Mac 安装磁盘映像未能卸载，请重试安装') from None
        if not os.path.ismount(mount):
            shutil.rmtree(mount)


class EngineInstaller:
    def __init__(self):
        self.manifest = DownloadManifest.model_validate_json((ROOT / 'engine-downloads.json').read_text())
        self.platform = current_platform()
        self.task = None
        self.state = 'idle'
        self.tier = None
        self.downloaded = 0
        self.total = None
        self.message = '选择分析模型后下载安装。'

    def homebrew_prefix(self):
        if self.platform == 'macos-arm64':
            return Path('/opt/homebrew')
        if self.platform == 'macos-x64':
            return Path('/usr/local')
        return None

    def local_engine(self, settings):
        candidates = [settings.katago_path, shutil.which('katago')]
        prefix = self.homebrew_prefix()
        if prefix:
            candidates.append(str(prefix / 'bin' / 'katago'))
        for candidate in candidates:
            if candidate and executable_file(Path(candidate)):
                return Path(candidate)
        return None

    def local_models(self, settings, tier):
        filename = Path(urlparse(self.manifest.models[tier].url).path).name
        candidates = []
        if settings.katago_model_path:
            configured = Path(settings.katago_model_path)
            if configured.is_absolute() and configured.name == filename:
                candidates.append(configured)
        prefix = self.homebrew_prefix()
        if prefix:
            candidates.append(prefix / 'share' / 'katago' / filename)
        return candidates

    def model_path(self, tier):
        model = self.manifest.models[tier]
        return DATA / 'models' / Path(urlparse(model.url).path).name

    def paths(self, tier):
        engine = self.manifest.engines[self.platform]
        return self.engine_directory() / engine.executable, self.model_path(tier)

    def engine_directory(self):
        engine = self.manifest.engines[self.platform]
        folder = DATA / 'engines' / f'{self.manifest.engineVersion}-{self.platform}-{engine.sha256}'
        return folder

    def installed_tier(self, settings):
        if not settings.katago_path or not executable_file(Path(settings.katago_path)):
            return None
        for tier, model in self.manifest.models.items():
            if not ready(model):
                continue
            weights = self.model_path(tier)
            if (
                settings.katago_model_path == str(weights) and weights.is_file()
            ):
                return tier
        return None

    def label_settings(self, settings):
        tier = self.installed_tier(settings)
        if tier is None:
            return replace(settings, engine_label=Settings().engine_label)
        model = self.manifest.models[tier]
        if ready(self.manifest.engines.get(self.platform)) and settings.katago_path == str(self.paths(tier)[0]):
            return replace(settings, engine_label=f'KataGo {self.manifest.engineVersion} · {model.name}')
        return replace(settings, engine_label=f'KataGo · {model.name}（本机引擎）')

    def unavailable(self, tier, settings):
        if self.platform == 'unsupported':
            return '当前系统暂不支持自动安装，请使用高级设置。'
        if not ready(self.manifest.models.get(tier)):
            return '此模型的下载校验信息暂未补齐，当前无法自动安装。'
        if self.local_engine(settings):
            return ''
        package = self.manifest.engines.get(self.platform)
        if not ready(package):
            return '未找到本机 KataGo，当前系统的引擎安装包也暂未提供。已有引擎可在高级设置中填写路径后保存，再重新读取安装状态。'
        if package.minimumMacOS:
            version = platform.mac_ver()[0]
            if not version:
                return '无法识别 macOS 版本，请在高级设置中配置已有的兼容引擎。'
            current = tuple(int(value) for value in version.split('.')[:2])
            minimum = tuple(int(value) for value in package.minimumMacOS.split('.'))
            if current < minimum:
                return f'此 Mac 引擎包要求 macOS {package.minimumMacOS} 或更新系统，当前为 {version}。可在高级设置中配置兼容的现有引擎。'
        return ''

    def status(self, settings):
        options = []
        for tier, (name, description) in TIER_TEXT.items():
            message = self.unavailable(tier, settings)
            available = not message
            if available and self.local_engine(settings):
                message = '已找到本机 KataGo，将复用引擎并下载所选模型；已存在的同名模型通过校验后也会复用。'
            elif available and self.platform.startswith('macos-'):
                backend = 'Metal' if self.platform == 'macos-arm64' else 'OpenCL'
                minimum = self.manifest.engines[self.platform].minimumMacOS
                message = f'将从 KaTrain 发布包安装 KataGo（{backend}，macOS {minimum}+）及所选模型，无需 Homebrew。仅调用包内引擎，不启动 KaTrain。'
            options.append({
                'tier': tier, 'name': name, 'description': description,
                'available': available, 'message': message
            })
        return {
            'platform': self.platform,
            'options': options,
            'installedTier': self.installed_tier(settings),
            'state': self.state, 'tier': self.tier,
            'downloadedBytes': self.downloaded, 'totalBytes': self.total,
            'message': self.message,
            'katagoPath': settings.katago_path, 'katagoModelPath': settings.katago_model_path
        }

    async def download(self, client, asset, target):
        target.parent.mkdir(parents=True, exist_ok=True)
        self.downloaded = 0
        self.total = asset.size
        if await run_in_threadpool(verified, target, asset):
            self.downloaded = asset.size
            return
        partial = target.with_suffix(target.suffix + '.part')
        digest = hashlib.sha256()
        try:
            async with asyncio.timeout(1800):
                async with client.stream('GET', asset.url) as response:
                    if response.status_code != 200 or response.url.scheme != 'https':
                        raise ValueError('无法下载文件，请稍后重试')
                    with partial.open('wb') as output:
                        async for chunk in response.aiter_bytes():
                            self.downloaded += len(chunk)
                            if self.downloaded > asset.size:
                                raise ValueError('下载文件大小不符，请重试')
                            output.write(chunk)
                            digest.update(chunk)
                            await asyncio.sleep(0)
            if self.downloaded != asset.size or digest.hexdigest() != asset.sha256:
                raise ValueError('下载文件校验失败，请重试')
            os.replace(partial, target)
        finally:
            partial.unlink(missing_ok=True)

    async def run(self, tier, lock, configure, binary, local_models):
        try:
            model = self.manifest.models[tier]
            weights = self.model_path(tier)
            mounts = await run_in_threadpool(download_mounts)
            async with httpx.AsyncClient(
                trust_env=True, follow_redirects=True, timeout=60,
                mounts=mounts,
                headers={'Accept-Encoding': 'identity'}
            ) as client:
                if binary is None:
                    engine = self.manifest.engines[self.platform]
                    binary, weights = self.paths(tier)
                    archive = DATA / 'downloads' / f'{engine.sha256}.{engine.format}'
                    self.state = 'downloading-engine'
                    self.message = '正在下载围棋分析引擎…'
                    await self.download(client, engine, archive)
                    self.state = 'extracting'
                    self.message = '正在安装围棋分析引擎…'
                    if engine.format == 'dmg':
                        await run_in_threadpool(extract_mac_engine, archive, self.engine_directory(), engine)
                    else:
                        await run_in_threadpool(extract_engine, archive, self.engine_directory(), engine.executable)
                self.state = 'downloading-model'
                self.message = '正在检查本机是否已有所选模型…'
                self.downloaded = 0
                self.total = None
                reused = await run_in_threadpool(reuse_model, local_models, weights, model)
                if reused:
                    self.downloaded = model.size
                    self.total = model.size
                else:
                    self.message = '正在下载所选分析模型…'
                    await self.download(client, model, weights)
            if not executable_file(binary):
                raise ValueError('引擎程序不存在或不可执行')
            self.state = 'configuring'
            self.message = '正在保存引擎配置…'
            await configure(str(binary), str(weights))
            self.state = 'completed'
            self.message = '安装完成。请点击“保存并测试”确认引擎与 AI 是否可用。'
        except asyncio.CancelledError:
            self.state = 'failed'
            self.message = '安装已中断，请重新下载安装；原有配置已保留。'
            raise
        except (httpx.HTTPError, TimeoutError):
            self.state = 'failed'
            self.message = '下载连接失败或超时，请重试；原有配置已保留。'
        except EngineInstallError as error:
            self.state = 'failed'
            self.message = f'{error}；原有配置已保留。'
        except (ValueError, zipfile.BadZipFile):
            self.state = 'failed'
            self.message = '安装文件大小、校验或内容不符合要求，请重试；原有配置已保留。'
        except Exception:
            self.state = 'failed'
            self.message = '安装未完成，请检查本机存储空间和写入权限后重试；原有配置已保留。'
        finally:
            lock.release()

    async def start(self, tier, lock, configure, settings):
        message = self.unavailable(tier, settings)
        if message:
            raise AppError('ENGINE_NOT_AVAILABLE', message, 503)
        if lock.locked():
            raise AppError('ENGINE_BUSY', '正在安装、分析或测试，请完成后重试', 409)
        await lock.acquire()
        self.tier = tier
        self.state = 'downloading-engine'
        self.downloaded = 0
        self.total = None
        self.message = '正在准备下载…'
        self.task = asyncio.create_task(self.run(
            tier, lock, configure, self.local_engine(settings), self.local_models(settings, tier)
        ))

    async def close(self):
        if self.task and not self.task.done():
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
