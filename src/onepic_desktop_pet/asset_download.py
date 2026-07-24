"""Public pet asset release discovery, secure ZIP installation, and Qt downloading."""

from __future__ import annotations

import hashlib
import json
import shutil
import stat
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path, PurePosixPath
from typing import Any, Mapping
from urllib.parse import urlencode, urlsplit
from zipfile import BadZipFile, ZipFile, ZipInfo

from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from .cloud_types import normalize_base_url
from .domain import PetProfile
from .pet_assets import PetAssetCatalog, PetAssetIdentity


@dataclass(frozen=True)
class AssetReleaseMetadata:
    release_id: str
    template_id: str
    template_version: str
    identity_version: str
    asset_version: str
    package_sha256: str
    package_size: int
    download_url: str
    manifest: Mapping[str, Any]

    @property
    def identity(self) -> PetAssetIdentity:
        return PetAssetIdentity(
            self.template_id,
            self.identity_version,
            self.asset_version,
        )

    @classmethod
    def from_payload(cls, payload: object) -> "AssetReleaseMetadata":
        if not isinstance(payload, dict):
            raise ValueError("形象发布元数据必须是 JSON 对象")

        def required_string(name: str) -> str:
            value = payload.get(name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"形象发布元数据缺少 {name}")
            return value.strip()

        package_sha256 = required_string("package_sha256").lower()
        if len(package_sha256) != 64 or any(
            char not in "0123456789abcdef" for char in package_sha256
        ):
            raise ValueError("形象包 SHA-256 格式无效")
        package_size = payload.get("package_size")
        if isinstance(package_size, bool) or not isinstance(package_size, int) or package_size <= 0:
            raise ValueError("形象包大小必须是正整数")
        download_url = required_string("download_url")
        parsed = urlsplit(download_url)
        if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment:
            raise ValueError("形象包下载地址必须是同源相对路径")
        if not download_url.startswith("/api/v1/assets/releases/"):
            raise ValueError("形象包下载地址不在允许的 API 路径")
        manifest = payload.get("manifest")
        if not isinstance(manifest, dict):
            raise ValueError("形象发布元数据缺少 Manifest")
        return cls(
            release_id=required_string("release_id"),
            template_id=required_string("template_id"),
            template_version=required_string("template_version"),
            identity_version=required_string("identity_version"),
            asset_version=required_string("asset_version"),
            package_sha256=package_sha256,
            package_size=package_size,
            download_url=download_url,
            manifest=manifest,
        )


def _safe_zip_name(value: str) -> str:
    raw = value.replace("\\", "/")
    path = PurePosixPath(raw)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("形象包包含不安全路径")
    if ":" in path.parts[0]:
        raise ValueError("形象包路径不得包含驱动器或 URL")
    return path.as_posix()


def _is_symlink(info: ZipInfo) -> bool:
    return stat.S_ISLNK((info.external_attr >> 16) & 0xFFFF)


def install_asset_package_zip(
    data: bytes,
    metadata: AssetReleaseMetadata,
    catalog: PetAssetCatalog,
    *,
    max_uncompressed_bytes: int = 128 * 1024 * 1024,
    max_files: int = 512,
) -> Path:
    if len(data) != metadata.package_size:
        raise ValueError("下载的形象包大小与发布元数据不一致")
    if hashlib.sha256(data).hexdigest() != metadata.package_sha256:
        raise ValueError("下载的形象包哈希与发布元数据不一致")
    try:
        archive = ZipFile(BytesIO(data))
    except BadZipFile as exc:
        raise ValueError("下载内容不是有效 ZIP 形象包") from exc

    download_root = catalog.cache_root / ".downloads"
    temporary = download_root / f"{metadata.release_id}.installing"
    shutil.rmtree(temporary, ignore_errors=True)
    temporary.mkdir(parents=True, exist_ok=True)
    try:
        with archive:
            infos = archive.infolist()
            files = [info for info in infos if not info.is_dir()]
            if len(files) > max_files:
                raise ValueError("形象包文件数量超过限制")
            if sum(info.file_size for info in files) > max_uncompressed_bytes:
                raise ValueError("形象包解压大小超过限制")
            names: set[str] = set()
            for info in infos:
                name = _safe_zip_name(info.filename)
                if name in names:
                    raise ValueError(f"形象包包含重复路径：{name}")
                names.add(name)
                if info.flag_bits & 0x1:
                    raise ValueError("形象包不得包含加密文件")
                if _is_symlink(info):
                    raise ValueError("形象包不得包含符号链接")
                if info.is_dir():
                    (temporary / name).mkdir(parents=True, exist_ok=True)
                    continue
                target = temporary / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.read(info))
        manifest_path = temporary / "manifest.json"
        if not manifest_path.is_file():
            raise ValueError("形象包根目录缺少 manifest.json")
        return catalog.install_package(manifest_path, expected=metadata.identity)
    finally:
        shutil.rmtree(temporary, ignore_errors=True)


class AssetPackageDownloadController(QObject):
    """Download missing exact pet asset packages from the public catalog."""

    package_installed = Signal(str, str, str, str)
    download_failed = Signal(str, str)
    status_message = Signal(str)

    def __init__(
        self,
        base_url: str,
        catalog: PetAssetCatalog,
        *,
        manager: QNetworkAccessManager | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._base_url = normalize_base_url(base_url)
        self.catalog = catalog
        self._manager = manager or QNetworkAccessManager(self)
        self._operations: dict[QNetworkReply, tuple[str, object]] = {}
        self._pending: set[tuple[str, str, str]] = set()

    def set_base_url(self, value: str) -> None:
        self._base_url = normalize_base_url(value)

    def request_for(self, profile: PetProfile) -> bool:
        identity = PetAssetIdentity(
            profile.identity.template_id,
            profile.identity.identity_version,
            profile.asset_version,
        )
        if self.catalog.selection_for(profile).exact:
            return False
        if identity.key in self._pending:
            return True
        self._pending.add(identity.key)
        query = urlencode(
            {
                "template_id": identity.template_id,
                "identity_version": identity.identity_version,
                "asset_version": identity.asset_version,
            }
        )
        request = QNetworkRequest(
            QUrl(f"{self._base_url}/api/v1/catalog/pet-assets?{query}")
        )
        request.setRawHeader(b"Accept", b"application/json")
        request.setRawHeader(b"User-Agent", b"MyPets-Desktop/0.1")
        reply = self._manager.get(request)
        self._operations[reply] = ("metadata", identity)
        reply.finished.connect(lambda reply=reply: self._finish(reply))
        self.status_message.emit(f"正在获取 {identity.template_id} 的形象版本")
        return True

    def _finish(self, reply: QNetworkReply) -> None:
        operation, context = self._operations.pop(reply, ("unknown", None))
        status_value = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
        status = int(status_value) if status_value is not None else 0
        raw = bytes(reply.readAll())
        error = reply.error()
        error_text = reply.errorString()
        reply.deleteLater()

        identity = context.identity if isinstance(context, AssetReleaseMetadata) else context
        if not isinstance(identity, PetAssetIdentity):
            return
        if error != QNetworkReply.NetworkError.NoError or not 200 <= status < 300:
            self._pending.discard(identity.key)
            self.download_failed.emit(identity.template_id, error_text or "形象包下载失败")
            return
        try:
            if operation == "metadata":
                metadata = AssetReleaseMetadata.from_payload(json.loads(raw.decode("utf-8")))
                if metadata.identity != identity:
                    raise ValueError("发布元数据身份与请求不一致")
                request = QNetworkRequest(QUrl(f"{self._base_url}{metadata.download_url}"))
                request.setRawHeader(b"Accept", b"application/zip")
                request.setRawHeader(b"User-Agent", b"MyPets-Desktop/0.1")
                package_reply = self._manager.get(request)
                self._operations[package_reply] = ("package", metadata)
                package_reply.finished.connect(
                    lambda reply=package_reply: self._finish(reply)
                )
                self.status_message.emit(f"正在下载 {identity.template_id} 的形象包")
                return
            if operation == "package" and isinstance(context, AssetReleaseMetadata):
                manifest = install_asset_package_zip(raw, context, self.catalog)
                self._pending.discard(identity.key)
                self.package_installed.emit(
                    identity.template_id,
                    identity.identity_version,
                    identity.asset_version,
                    str(manifest),
                )
                self.status_message.emit(f"已安装 {identity.template_id} 的形象包")
                return
            raise ValueError("未知形象包下载操作")
        except (OSError, ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            self._pending.discard(identity.key)
            self.download_failed.emit(identity.template_id, str(exc))
