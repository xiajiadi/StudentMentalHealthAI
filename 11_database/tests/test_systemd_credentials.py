"""Synthetic-only systemd reader checks; native Linux coverage is explicitly marked."""

from __future__ import annotations

import json
import os
import stat
import sys
import traceback
from pathlib import PurePosixPath
from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet
from database_layer import LinuxSystemdCredentialKeyProvider, crypto, read_linux_systemd_credential
from database_layer.crypto import FernetDataProtectionProvider
from database_layer.errors import EncryptionKeyUnavailable

DIRECTORY = "/run/credentials/psynova-synthetic.service"
NAME = "database-keys.json"
ERROR = "Linux systemd encryption credential is unavailable or invalid"


class PosixCredentials:
    """Descriptor filesystem double, not evidence of native Linux enforcement."""

    O_RDONLY = 0
    O_DIRECTORY = 1
    O_NOFOLLOW = 2
    O_CLOEXEC = 4
    O_NONBLOCK = 8
    name = "posix"

    def __init__(self):
        self.environ = {"CREDENTIALS_DIRECTORY": DIRECTORY}
        self.key = Fernet.generate_key()
        self.content = json.dumps(
            {"active_version": "synthetic-v1", "keys": {"synthetic-v1": self.key.decode()}}
        ).encode()
        self.nodes = {}
        for path in ["/", "/run", "/run/credentials", DIRECTORY]:
            self.nodes[path] = self.metadata(stat.S_IFDIR | 0o700)
        self.nodes[DIRECTORY + "/" + NAME] = self.metadata(stat.S_IFREG | 0o400)
        self.descriptors = {}
        self.calls = []
        self.next_fd = 10
        self.offset = 0
        self.after_read = None

    def metadata(self, mode):
        return SimpleNamespace(
            st_mode=mode,
            st_uid=1001,
            st_gid=1001,
            st_nlink=1,
            st_size=len(self.content),
            st_dev=1,
            st_ino=len(self.nodes),
            st_mtime_ns=1,
            st_ctime_ns=1,
        )

    def geteuid(self):
        return 1001

    def open(self, name, flags, *, dir_fd=None):
        assert flags & self.O_NOFOLLOW
        assert flags & self.O_CLOEXEC
        assert flags in {
            self.O_DIRECTORY | self.O_NOFOLLOW | self.O_CLOEXEC,
            self.O_NOFOLLOW | self.O_CLOEXEC | self.O_NONBLOCK,
        }
        path = name if dir_fd is None else str(PurePosixPath(self.descriptors[dir_fd]) / name)
        self.calls.append(path)
        node = self.nodes.get(path)
        if node is None or stat.S_ISLNK(node.st_mode):
            raise OSError("SYNTHETIC_PATH_EXCEPTION_SENTINEL")
        if flags & self.O_DIRECTORY and not stat.S_ISDIR(node.st_mode):
            raise NotADirectoryError("SYNTHETIC_PATH_EXCEPTION_SENTINEL")
        descriptor = self.next_fd
        self.next_fd += 1
        self.descriptors[descriptor] = path
        return descriptor

    def fstat(self, descriptor):
        return SimpleNamespace(**vars(self.nodes[self.descriptors[descriptor]]))

    def read(self, descriptor, size):
        credential_name = self.environ.get("DATABASE_KEY_FILE", NAME)
        assert self.descriptors[descriptor] == DIRECTORY + "/" + credential_name
        chunk = self.content[self.offset : self.offset + size]
        self.offset += len(chunk)
        if self.after_read is not None:
            self.after_read()
        return chunk

    def close(self, descriptor):
        del self.descriptors[descriptor]


@pytest.fixture
def credentials(monkeypatch):
    fake = PosixCredentials()
    monkeypatch.setattr(crypto, "os", fake)
    monkeypatch.setattr(crypto, "sys", SimpleNamespace(platform="linux"))
    monkeypatch.setattr(crypto, "Path", PurePosixPath)
    yield fake
    assert fake.descriptors == {}


def reject():
    with pytest.raises(EncryptionKeyUnavailable) as caught:
        LinuxSystemdCredentialKeyProvider.from_env()
    assert str(caught.value) == ERROR
    assert caught.value.__cause__ is None
    rendered = "".join(traceback.format_exception(caught.value))
    assert "SYNTHETIC_PATH_EXCEPTION_SENTINEL" not in rendered
    assert DIRECTORY not in rendered


@pytest.mark.parametrize("directory_mode", [0o500, 0o700])
@pytest.mark.parametrize("file_mode", [0o400, 0o600])
def test_valid_simulated_posix_round_trip_and_read_only(credentials, directory_mode, file_mode):
    credentials.nodes[DIRECTORY].st_mode = stat.S_IFDIR | directory_mode
    credentials.nodes[DIRECTORY + "/" + NAME].st_mode = stat.S_IFREG | file_mode
    provider = LinuxSystemdCredentialKeyProvider.from_env()
    assert provider.active_version == "synthetic-v1"
    assert provider.versions() == ("synthetic-v1",)
    assert provider.get_key("synthetic-v1") == credentials.key
    protection = FernetDataProtectionProvider(provider)
    payload = protection.encrypt_json({"synthetic": True}, payload_schema_version="test.v1")
    assert protection.decrypt_json(payload) == {"synthetic": True}
    assert credentials.calls[-1] == DIRECTORY + "/" + NAME
    assert not hasattr(provider, "path")
    with pytest.raises(EncryptionKeyUnavailable) as caught:
        provider.get_key("SYNTHETIC_VERSION_SENTINEL")
    assert str(caught.value) == ERROR
    assert caught.value.__cause__ is None


def test_generic_systemd_reader_returns_only_the_named_credential_bytes(credentials):
    assert read_linux_systemd_credential(NAME) == credentials.content


@pytest.mark.parametrize(
    ("directory_mode", "owner_permissions"),
    [(0o550, "r-x"), (0o750, "rwx")],
)
def test_accepts_systemd_root_owned_credentials_with_exact_service_acl(
    credentials, monkeypatch, directory_mode, owner_permissions
):
    directory = credentials.nodes[DIRECTORY]
    key_file = credentials.nodes[DIRECTORY + "/" + NAME]
    directory.st_uid = key_file.st_uid = 0
    directory.st_gid = key_file.st_gid = 0
    directory.st_mode = stat.S_IFDIR | directory_mode
    key_file.st_mode = stat.S_IFREG | 0o440

    def read_acl(descriptor):
        path = credentials.descriptors[descriptor]
        if path == DIRECTORY:
            return (
                f"user::{owner_permissions}",
                "user:1001:r-x",
                "group::---",
                "mask::r-x",
                "other::---",
            )
        if path == DIRECTORY + "/" + NAME:
            return (
                "user::r--",
                "user:1001:r--",
                "group::---",
                "mask::r--",
                "other::---",
            )
        raise AssertionError("ACL should only be inspected for final systemd credential objects")

    monkeypatch.setattr(crypto, "_read_posix_acl", read_acl)
    provider = LinuxSystemdCredentialKeyProvider.from_env()
    assert provider.active_version == "synthetic-v1"
    assert provider.get_key("synthetic-v1") == credentials.key


@pytest.mark.parametrize(
    "file_acl",
    [
        ("user::r--", "user:1001:rw-", "group::---", "mask::rw-", "other::---"),
        ("user::r--", "user:1002:r--", "group::---", "mask::r--", "other::---"),
        (
            "user::r--",
            "user:1001:r--",
            "group::r--",
            "mask::r--",
            "other::---",
        ),
    ],
)
def test_rejects_root_owned_systemd_credential_acls_with_extra_access(
    credentials, monkeypatch, file_acl
):
    directory = credentials.nodes[DIRECTORY]
    key_file = credentials.nodes[DIRECTORY + "/" + NAME]
    directory.st_uid = key_file.st_uid = 0
    directory.st_gid = key_file.st_gid = 0
    directory.st_mode = stat.S_IFDIR | 0o750
    key_file.st_mode = stat.S_IFREG | 0o440

    def read_acl(descriptor):
        path = credentials.descriptors[descriptor]
        if path == DIRECTORY:
            return (
                "user::rwx",
                "user:1001:r-x",
                "group::---",
                "mask::r-x",
                "other::---",
            )
        return file_acl

    monkeypatch.setattr(crypto, "_read_posix_acl", read_acl)
    reject()


@pytest.mark.parametrize("value", [None, "", " ", "relative", "/", "/run/../credentials"])
def test_requires_explicit_absolute_directory(credentials, value):
    if value is None:
        credentials.environ.pop("CREDENTIALS_DIRECTORY")
    else:
        credentials.environ["CREDENTIALS_DIRECTORY"] = value
    reject()
    assert credentials.calls == []


@pytest.mark.parametrize(
    "value",
    ["", " ", "..", "../key", "sub/key", "/tmp/key", "a/../key", "a\\key", "~key", "é", "a" * 129],
)
def test_rejects_names_that_could_escape_credentials_directory(credentials, value):
    credentials.environ["DATABASE_KEY_FILE"] = value
    reject()
    assert credentials.calls == []


def test_explicit_credential_name(credentials):
    alternate = "school-db.keys"
    credentials.environ["DATABASE_KEY_FILE"] = alternate
    credentials.nodes[DIRECTORY + "/" + alternate] = credentials.nodes[DIRECTORY + "/" + NAME]
    provider = LinuxSystemdCredentialKeyProvider.from_env()
    assert provider.active_version == "synthetic-v1"
    assert credentials.calls[-1] == DIRECTORY + "/" + alternate


@pytest.mark.parametrize("path", [DIRECTORY, DIRECTORY + "/" + NAME])
def test_missing_runtime_material_fails_closed(credentials, path):
    del credentials.nodes[path]
    reject()


@pytest.mark.parametrize("path", ["/run", DIRECTORY, DIRECTORY + "/" + NAME])
def test_symlinks_in_file_directory_or_ancestor_are_rejected(credentials, path):
    credentials.nodes[path].st_mode = stat.S_IFLNK | 0o700
    reject()


@pytest.mark.parametrize("mode", [0o640, 0o604, 0o644, 0o666, 0o700, 0o4600, 0o000])
def test_unsafe_file_permissions(credentials, mode):
    credentials.nodes[DIRECTORY + "/" + NAME].st_mode = stat.S_IFREG | mode
    reject()


@pytest.mark.parametrize("mode", [0o750, 0o705, 0o777, 0o1700, 0o600, 0o000])
def test_unsafe_directory_permissions(credentials, mode):
    credentials.nodes[DIRECTORY].st_mode = stat.S_IFDIR | mode
    reject()


@pytest.mark.parametrize("path", [DIRECTORY, DIRECTORY + "/" + NAME])
@pytest.mark.parametrize("owner", [0, 1002])
def test_wrong_owner_including_root_is_rejected(credentials, path, owner):
    credentials.nodes[path].st_uid = owner
    reject()


@pytest.mark.parametrize("kind", [stat.S_IFDIR, stat.S_IFIFO, stat.S_IFCHR, stat.S_IFSOCK])
def test_credential_must_be_regular_file(credentials, kind):
    credentials.nodes[DIRECTORY + "/" + NAME].st_mode = kind | 0o400
    reject()


@pytest.mark.parametrize("links", [0, 2])
def test_credential_must_have_one_link(credentials, links):
    credentials.nodes[DIRECTORY + "/" + NAME].st_nlink = links
    reject()


@pytest.mark.parametrize("size", [0, crypto._MAX_SYSTEMD_CREDENTIAL_BYTES + 1])
def test_file_size_is_bounded_before_reading(credentials, size):
    credentials.nodes[DIRECTORY + "/" + NAME].st_size = size
    reject()
    assert credentials.offset == 0


def test_read_is_bounded_even_if_file_grows(credentials):
    credentials.content = b"x" * (crypto._MAX_SYSTEMD_CREDENTIAL_BYTES + 100)
    reject()
    assert credentials.offset == crypto._MAX_SYSTEMD_CREDENTIAL_BYTES + 1


def test_changed_file_metadata_is_rejected(credentials):
    def change_owner():
        credentials.nodes[DIRECTORY + "/" + NAME].st_uid = 1002

    credentials.after_read = change_owner
    reject()


@pytest.mark.parametrize("field", ["st_mode", "st_uid"])
def test_directory_access_changed_during_read_is_rejected(credentials, field):
    def change_directory():
        setattr(
            credentials.nodes[DIRECTORY],
            field,
            stat.S_IFDIR | 0o777 if field == "st_mode" else 1002,
        )

    credentials.after_read = change_directory
    reject()


@pytest.mark.parametrize("duplicate", ["active_version", "keys", "key-version"])
def test_duplicate_fields_are_rejected_even_if_last_value_would_be_valid(credentials, duplicate):
    encoded_key = json.dumps(credentials.key.decode())
    key_object = '{"synthetic-v1":' + encoded_key + "}"
    if duplicate == "active_version":
        content = (
            '{"active_version":"old","active_version":"synthetic-v1","keys":' + key_object + "}"
        )
    elif duplicate == "keys":
        content = '{"active_version":"synthetic-v1","keys":{},"keys":' + key_object + "}"
    else:
        content = (
            '{"active_version":"synthetic-v1","keys":{'
            '"synthetic-v1":"invalid","synthetic-v1":' + encoded_key + "}}"
        )
    credentials.content = content.encode()
    credentials.nodes[DIRECTORY + "/" + NAME].st_size = len(credentials.content)
    reject()


@pytest.mark.parametrize(
    "content",
    [
        b"",
        b"not-json",
        b"\xff",
        b"[]",
        b"null",
        b"{}",
        b'{"active_version":"v1","keys":{}}',
        b'{"active_version":1,"keys":{"v1":"x"}}',
        b'{"active_version":"v1","keys":{"v1":1}}',
        b'{"active_version":"v1","keys":{"v1":"invalid"}}',
        b'{"active_version":"v1","keys":{"v1":"invalid"},"extra":true}',
        b'{"active_version":"v1","active_version":"v2","keys":{}}',
        b'{"active_version":"v1","keys":{"v1":"a","v1":"b"}}',
    ],
)
def test_malformed_payload_is_sanitized(credentials, content):
    credentials.content = content
    credentials.nodes[DIRECTORY + "/" + NAME].st_size = len(content)
    reject()


@pytest.mark.parametrize(
    "variant", ["missing-active", "empty-version", "noncanonical", "extra-key"]
)
def test_schema_and_actual_fernet_material_are_validated(credentials, variant):
    key = credentials.key.decode()
    payload = {"active_version": "synthetic-v1", "keys": {"synthetic-v1": key}}
    if variant == "missing-active":
        payload["active_version"] = "missing"
    elif variant == "empty-version":
        payload["keys"][""] = key
    elif variant == "noncanonical":
        payload["keys"]["synthetic-v1"] = key + "!"
    else:
        payload["keys"]["old"] = "invalid"
    credentials.content = json.dumps(payload).encode()
    credentials.nodes[DIRECTORY + "/" + NAME].st_size = len(credentials.content)
    reject()


@pytest.mark.parametrize(("os_name", "platform"), [("nt", "win32"), ("posix", "darwin")])
def test_non_linux_platform_is_unsupported(credentials, monkeypatch, os_name, platform):
    credentials.name = os_name
    monkeypatch.setattr(crypto, "sys", SimpleNamespace(platform=platform))
    reject()
    assert credentials.calls == []


@pytest.mark.skipif(os.name != "posix" or sys.platform != "linux", reason="native Linux only")
def test_native_linux_round_trip_and_filesystem_rejections(tmp_path, monkeypatch):
    directory = tmp_path / "credentials"
    directory.mkdir(mode=0o700)
    key_file = directory / NAME
    key_file.write_text(
        json.dumps(
            {
                "active_version": "synthetic-v1",
                "keys": {"synthetic-v1": Fernet.generate_key().decode()},
            }
        )
    )
    key_file.chmod(0o400)
    monkeypatch.setenv("CREDENTIALS_DIRECTORY", str(directory))
    monkeypatch.delenv("DATABASE_KEY_FILE", raising=False)
    original = key_file.read_bytes()
    provider = LinuxSystemdCredentialKeyProvider.from_env()
    protection = FernetDataProtectionProvider(provider)
    payload = protection.encrypt_json({"synthetic": True}, payload_schema_version="test.v1")
    assert protection.decrypt_json(payload) == {"synthetic": True}
    assert original == key_file.read_bytes()
    key_file.chmod(0o640)
    reject()
    key_file.chmod(0o400)
    hardlink = directory / "second-link"
    os.link(key_file, hardlink)
    reject()
    hardlink.unlink()
    target = directory / "target"
    key_file.rename(target)
    key_file.symlink_to(target)
    reject()
