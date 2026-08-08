#!/usr/bin/env python3
"""State and evidence controller for the material-code-review skill.

The tool intentionally uses only the Python standard library. It enforces
scope freshness, schema-critical fields, user-gate receipts, exact repair
boundaries, test logging, local checkpoints, and bounded post-fix repair.
It does not attempt to replace human or model judgment about code semantics.
"""

from __future__ import annotations

import argparse
import copy
import difflib
import errno
import hashlib
import json
import os
import re
import signal
import shutil
import stat
import struct
import subprocess
import sys
import tempfile
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence

SCRIPT_DIRECTORY = Path(__file__).resolve().parent
if str(SCRIPT_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIRECTORY))

from obligation_contract import (  # noqa: E402
    CANDIDATE_SET_SCHEMA as OBLIGATION_CANDIDATE_SET_SCHEMA,
    COVERAGE_PLAN_SCHEMA as OBLIGATION_COVERAGE_PLAN_SCHEMA,
    ObligationContractError,
    canonical_git_path,
    check_contracts_for_assignment,
    required_assignment_ids,
    scenario_checks_for_assignment,
    validate_assignment_result,
    validate_coverage_contract,
)


TOOL_VERSION = "1.7.0"
MATERIAL_REVIEW_STATE_SCHEMA = "material-review/state/v6"
LEGACY_MATERIAL_REVIEW_STATE_SCHEMA_V5 = "material-review/state/v5"
LEGACY_MATERIAL_REVIEW_STATE_SCHEMA_V4 = "material-review/state/v4"
LEGACY_MATERIAL_REVIEW_STATE_SCHEMA_V3 = "material-review/state/v3"
LEGACY_MATERIAL_REVIEW_STATE_SCHEMA_V2 = "material-review/state/v2"
LEGACY_MATERIAL_REVIEW_STATE_SCHEMA_V1 = "material-review/state/v1"
SIMPLIFICATION_STATE_SCHEMA = "material-review/state/v1"
SCOPE_SCHEMA = "material-review/scope/v1"
CANDIDATE_SCHEMA = "material-review/candidate-set/v1"
CANDIDATE_SCHEMA_REVIEW = OBLIGATION_CANDIDATE_SET_SCHEMA
NORMALIZED_CANDIDATES_SCHEMA_REVIEW = "material-review/candidates-normalized/v6"
NORMALIZED_CANDIDATES_SCHEMA_SIMPLIFICATION = "material-review/candidates-normalized/v1"
ADJUDICATION_SCHEMA_REVIEW = "material-review/adjudication/v4"
ADJUDICATION_SCHEMA_SIMPLIFICATION = "material-review/adjudication/v3"
LEDGER_SCHEMA_REVIEW = "material-review/ledger/v4"
LEDGER_SCHEMA_SIMPLIFICATION = "material-review/ledger/v3"
FINDINGS_GATE_SCHEMA = "material-review/findings-gate/v1"
FIX_PLAN_SCHEMA = "material-review/fix-plan/v2"
PLAN_GATE_SCHEMA = "material-review/plan-gate/v1"
FIX_SUMMARY_SCHEMA = "material-review/fix-summary/v1"
VERIFICATION_SCHEMA = "material-review/verification/v1"
COVERAGE_PLAN_SCHEMA = OBLIGATION_COVERAGE_PLAN_SCHEMA
COVERAGE_CONTEXT_SCHEMA = "material-review/coverage-context/v1"
CHECKPOINT_SCHEMA_V4 = "material-review/checkpoint/v4"
SNAPSHOT_MATCHED_BYTES = "matched_bytes"
SNAPSHOT_MATCHED_MISSING = "matched_missing"
SNAPSHOT_NO_MATCH = "no_match"
WORKFLOW_PROFILE_REVIEW = "material_review"
SIMPLIFICATION_PROFILE = "material-code-simplification"
STATE_CONTRACT_MATERIAL_REVIEW = "current_material_review"
STATE_CONTRACT_SIMPLIFICATION = "current_simplification"
STATE_CONTRACT_FINALIZABLE_MATERIAL_REVIEW_V1 = "finalizable_material_review_v1"
STATE_CONTRACT_FINALIZABLE_MATERIAL_REVIEW_V2 = "finalizable_material_review_v2"
STATE_CONTRACT_LEGACY_MATERIAL_REVIEW_V5 = "legacy_material_review_v5"
STATE_CONTRACT_LEGACY_MATERIAL_REVIEW_V4 = "legacy_material_review_v4"
STATE_CONTRACT_LEGACY_MATERIAL_REVIEW_V3 = "legacy_material_review_v3"
STATE_CONTRACT_LEGACY_MATERIAL_REVIEW = "legacy_material_review"

RISK_ASSESSMENT_CODES = frozenset({"user_selectable_output_paths", "persisted_config_semantics"})
CORE_REVIEW_LENSES = frozenset({"correctness", "test_adequacy", "standards_alignment"})
REQUIRED_LENSES_BY_RISK = {
    "user_selectable_output_paths": frozenset({"reliability"}),
    "persisted_config_semantics": frozenset({"migration_data_safety", "api_config_compatibility"}),
}

PHASE_CONTEXT = "CONTEXT_FROZEN"
PHASE_CANDIDATES = "CANDIDATES_CAPTURED"
PHASE_ADJUDICATED = "ADJUDICATED"
PHASE_FINDINGS_APPROVED = "FINDINGS_APPROVED"
PHASE_PLAN_VALIDATED = "PLAN_VALIDATED"
PHASE_PLAN_APPROVED = "PLAN_APPROVED"
PHASE_FIXING = "FIXING"
PHASE_VERIFYING = "VERIFYING"
PHASE_REPAIR_REQUIRED = "REPAIR_REQUIRED"
PHASE_PLAN_AMENDMENT = "PLAN_AMENDMENT_REQUIRED"
PHASE_COMPLETE = "COMPLETE"
PHASE_ABORTED = "ABORTED"
PHASE_BLOCKED = "BLOCKED"

MUTATION_PHASES = {
    PHASE_FIXING,
    PHASE_VERIFYING,
    PHASE_REPAIR_REQUIRED,
    PHASE_PLAN_AMENDMENT,
    PHASE_BLOCKED,
}

NATURES = {"defect", "coverage_gap", "documentation_gap", "improvement", "risk"}
CATEGORIES = {
    "correctness",
    "security",
    "privacy",
    "reliability",
    "tests",
    "docs",
    "performance",
    "api_contract",
    "migration",
    "concurrency",
    "simplification",
    "dry",
    "architecture",
    "standards",
}
SEVERITIES = {"blocker", "high", "medium", "low"}
CONFIDENCES = {"certain", "high", "medium", "low"}
EVIDENCE_SIDES = {"comparison", "baseline", "diff"}
SCOPE_RELATIONS = {"primary", "secondary", "pre_existing"}
FIX_RISKS = {"low", "medium", "high", "unknown"}
REVIEW_MODES = {"subagent", "controller", "external"}
VALIDATION_MODES = {"independent", "controller_direct", "degraded_self_audit"}
VALIDATION_VERDICTS = {"confirmed", "rejected", "uncertain"}
CAUSALITIES = {"introduced", "exposed", "pre_existing", "uncertain"}
DISPOSITIONS = {"keep", "discard"}
RECOMMENDATIONS = {"fix_now", "defer", "monitor", "none"}
REPAIR_DIRECTION_STATUSES = {"reviewed", "needs_refinement", "needs_user_decision", "unsafe_to_apply", "insufficient_evidence"}
MERGE_VERDICTS = {
    "READY",
    "READY WITH OPTIONAL FOLLOW-UPS",
    "SHOULD FIX BEFORE MERGE",
    "NOT READY",
}
DISCARD_REASONS = {
    "DUPLICATE",
    "NOT_IN_SCOPE",
    "PRE_EXISTING_UNRELATED",
    "HANDLED_ELSEWHERE",
    "EVIDENCE_MISMATCH",
    "CONSEQUENCE_UNSUPPORTED",
    "VALIDATOR_REJECTED",
    "UNCERTAIN_BELOW_HIGH_IMPACT",
    "STYLE_OR_LINTER",
    "SPECULATIVE_FUTURE",
    "HARMLESS_DUPLICATION",
    "ABSTRACTION_COST_EXCEEDS_VALUE",
    "SIMPLIFICATION_NOT_MATERIAL",
    "TEST_GAP_NOT_FRAGILE",
    "DOC_MISMATCH_NOT_OPERATIONAL",
    "SETTLED_PREFERENCE",
    "OUTSIDE_REVIEWER_CONTRACT",
}

SEVERITY_ORDER = {"blocker": 0, "high": 1, "medium": 2, "low": 3}
CONFIDENCE_ORDER = {"certain": 0, "high": 1, "medium": 2, "low": 3}

TRANSIENT_RUNTIME_DIR_MARKERS = {
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".hypothesis",
    ".tox",
    ".nox",
    ".nyc_output",
}
TRANSIENT_RUNTIME_FILE_NAMES = {".ds_store", "thumbs.db", ".coverage"}
TRANSIENT_RUNTIME_SUFFIXES = (".pyc", ".pyo", ".pyd")
CANDIDATE_AUTHORITY_LOCK_TIMEOUT_SECONDS = 10.0
CANDIDATE_AUTHORITY_LOCK_POLL_SECONDS = 0.05


def is_transient_runtime_path(path: str) -> bool:
    normalized = path.replace("\\", "/").strip().lstrip("/")
    parts = [part for part in normalized.split("/") if part]
    if any(part in TRANSIENT_RUNTIME_DIR_MARKERS for part in parts):
        return True
    name = parts[-1].lower() if parts else ""
    return name in TRANSIENT_RUNTIME_FILE_NAMES or name.endswith(TRANSIENT_RUNTIME_SUFFIXES)


class ReviewError(RuntimeError):
    """Expected control failure with an actionable message."""


class _ArtifactTemporary:
    def __init__(self, name: str, descriptor: int) -> None:
        self.name = name
        self.descriptor = descriptor


class _PosixArtifactBackend:
    """No-follow, descriptor-relative artifact operations for POSIX hosts."""

    platform_name = "posix"

    def __init__(self) -> None:
        required_dir_fd = (os.open, os.stat, os.mkdir, os.unlink, os.rmdir)
        missing = [
            function.__name__
            for function in required_dir_fd
            if function not in os.supports_dir_fd
        ]
        if os.rename not in os.supports_dir_fd:
            missing.append("rename")
        if not hasattr(os, "O_DIRECTORY") or not hasattr(os, "O_NOFOLLOW"):
            missing.append("O_DIRECTORY/O_NOFOLLOW")
        if missing:
            raise ReviewError(
                "Artifact identity backend is unavailable before mutation; missing "
                + ", ".join(sorted(set(missing)))
            )

    @staticmethod
    def _directory_flags() -> int:
        return os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW

    def open_absolute_directory(
        self, path: Path, *, create: bool
    ) -> tuple[int, int, str]:
        absolute = Path(os.path.abspath(os.fspath(path)))
        if not absolute.is_absolute() or absolute == Path(absolute.anchor):
            raise ReviewError(f"Artifact authority requires a non-root absolute path: {path}")
        components = absolute.parts[1:]
        parent = os.open(absolute.anchor, self._directory_flags())
        try:
            for index, name in enumerate(components):
                if name in {"", ".", ".."} or "/" in name:
                    raise ReviewError(f"Unsafe artifact directory component: {name!r}")
                try:
                    child = os.open(name, self._directory_flags(), dir_fd=parent)
                except FileNotFoundError:
                    if not create:
                        raise
                    os.mkdir(name, 0o700, dir_fd=parent)
                    child = os.open(name, self._directory_flags(), dir_fd=parent)
                if index == len(components) - 1:
                    return parent, child, name
                os.close(parent)
                parent = child
        except BaseException:
            os.close(parent)
            raise
        raise AssertionError("artifact authority path had no components")

    def open_directory(
        self,
        parent: int,
        name: str,
        *,
        create: bool = False,
        exclusive: bool = False,
    ) -> int:
        if create and exclusive:
            os.mkdir(name, 0o700, dir_fd=parent)
            return os.open(name, self._directory_flags(), dir_fd=parent)
        try:
            return os.open(name, self._directory_flags(), dir_fd=parent)
        except FileNotFoundError:
            if not create:
                raise
            os.mkdir(name, 0o700, dir_fd=parent)
            return os.open(name, self._directory_flags(), dir_fd=parent)

    @staticmethod
    def close_directory(directory: int) -> None:
        os.close(directory)

    @staticmethod
    def identity(directory: int) -> tuple[int, int]:
        info = os.fstat(directory)
        return info.st_dev, info.st_ino

    @staticmethod
    def entry_kind(parent: int, name: str) -> str | None:
        try:
            info = os.stat(name, dir_fd=parent, follow_symlinks=False)
        except FileNotFoundError:
            return None
        if stat.S_ISLNK(info.st_mode):
            return "symlink"
        if stat.S_ISDIR(info.st_mode):
            return "directory"
        if stat.S_ISREG(info.st_mode):
            return "file"
        return "other"

    @staticmethod
    def read_bytes(parent: int, name: str) -> bytes:
        descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent)
        with os.fdopen(descriptor, "rb") as handle:
            return handle.read()

    @staticmethod
    def open_lock_descriptor(parent: int, name: str) -> int:
        return os.open(
            name,
            os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW,
            0o600,
            dir_fd=parent,
        )

    @staticmethod
    def create_temporary(parent: int, target_name: str, data: bytes) -> _ArtifactTemporary:
        temporary_name = f".{target_name}.{uuid.uuid4().hex}.tmp"
        descriptor = os.open(
            temporary_name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=parent,
        )
        try:
            with os.fdopen(descriptor, "wb", closefd=False) as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
        except BaseException:
            os.close(descriptor)
            try:
                os.unlink(temporary_name, dir_fd=parent)
            except FileNotFoundError:
                pass
            raise
        return _ArtifactTemporary(temporary_name, descriptor)

    @staticmethod
    def replace_temporary(
        parent: int, temporary: _ArtifactTemporary, target_name: str
    ) -> None:
        os.rename(
            temporary.name,
            target_name,
            src_dir_fd=parent,
            dst_dir_fd=parent,
        )

    @staticmethod
    def close_temporary(temporary: _ArtifactTemporary) -> None:
        os.close(temporary.descriptor)

    @staticmethod
    def cleanup_temporary(parent: int, temporary: _ArtifactTemporary) -> None:
        try:
            os.unlink(temporary.name, dir_fd=parent)
        except FileNotFoundError:
            pass

    @staticmethod
    def flush_directory(directory: int) -> None:
        os.fsync(directory)

    @staticmethod
    def list_names(directory: int) -> list[str]:
        return sorted(os.listdir(directory))

    def remove_entry(self, parent: int, name: str, *, recursive: bool) -> None:
        kind = self.entry_kind(parent, name)
        if kind is None:
            return
        if kind == "directory":
            directory = self.open_directory(parent, name)
            try:
                names = self.list_names(directory)
                if names and not recursive:
                    raise OSError(f"artifact directory is not empty: {name}")
                for child_name in names:
                    self.remove_entry(directory, child_name, recursive=True)
            finally:
                self.close_directory(directory)
            os.rmdir(name, dir_fd=parent)
            return
        os.unlink(name, dir_fd=parent)

    @staticmethod
    def rename_entry(parent: int, source_name: str, target_name: str) -> None:
        os.rename(
            source_name,
            target_name,
            src_dir_fd=parent,
            dst_dir_fd=parent,
        )


class _WindowsArtifactBackend:
    """Windows handle-relative artifact operations backed by documented NT APIs."""

    platform_name = "windows"

    FILE_LIST_DIRECTORY = 0x0001
    FILE_READ_DATA = 0x0001
    FILE_WRITE_DATA = 0x0002
    FILE_APPEND_DATA = 0x0004
    FILE_READ_ATTRIBUTES = 0x0080
    FILE_WRITE_ATTRIBUTES = 0x0100
    DELETE = 0x00010000
    SYNCHRONIZE = 0x00100000
    FILE_SHARE_READ = 0x00000001
    FILE_SHARE_WRITE = 0x00000002
    FILE_SHARE_DELETE = 0x00000004
    FILE_OPEN = 0x00000001
    FILE_CREATE = 0x00000002
    FILE_OPEN_IF = 0x00000003
    FILE_DIRECTORY_FILE = 0x00000001
    FILE_SYNCHRONOUS_IO_NONALERT = 0x00000020
    FILE_NON_DIRECTORY_FILE = 0x00000040
    FILE_OPEN_REPARSE_POINT = 0x00200000
    FILE_ATTRIBUTE_NORMAL = 0x00000080
    FILE_ATTRIBUTE_DIRECTORY = 0x00000010
    FILE_ATTRIBUTE_REPARSE_POINT = 0x00000400
    OBJ_CASE_INSENSITIVE = 0x00000040
    OPEN_EXISTING = 3
    FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
    FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
    FILE_ID_INFO_CLASS = 18
    FILE_ATTRIBUTE_TAG_INFO_CLASS = 9
    FILE_RENAME_INFO_CLASS = 3
    FILE_DISPOSITION_INFO_CLASS = 4
    FILE_DIRECTORY_INFORMATION_CLASS = 1
    STATUS_NO_MORE_FILES = 0x80000006
    STATUS_BUFFER_OVERFLOW = 0x80000005

    def __init__(self) -> None:
        if os.name != "nt":
            raise ReviewError("Windows artifact backend is available only on Windows")
        import ctypes
        from ctypes import wintypes

        self.ctypes = ctypes
        self.wintypes = wintypes
        self.ntdll = ctypes.WinDLL("ntdll", use_last_error=True)
        self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

        class UnicodeString(ctypes.Structure):
            _fields_ = [
                ("Length", wintypes.USHORT),
                ("MaximumLength", wintypes.USHORT),
                ("Buffer", wintypes.LPWSTR),
            ]

        class ObjectAttributes(ctypes.Structure):
            _fields_ = [
                ("Length", wintypes.ULONG),
                ("RootDirectory", wintypes.HANDLE),
                ("ObjectName", ctypes.POINTER(UnicodeString)),
                ("Attributes", wintypes.ULONG),
                ("SecurityDescriptor", wintypes.LPVOID),
                ("SecurityQualityOfService", wintypes.LPVOID),
            ]

        class IoStatusBlock(ctypes.Structure):
            _fields_ = [("Status", wintypes.LPVOID), ("Information", ctypes.c_size_t)]

        class FileId128(ctypes.Structure):
            _fields_ = [("Identifier", wintypes.BYTE * 16)]

        class FileIdInfo(ctypes.Structure):
            _fields_ = [
                ("VolumeSerialNumber", ctypes.c_ulonglong),
                ("FileId", FileId128),
            ]

        class FileAttributeTagInfo(ctypes.Structure):
            _fields_ = [("FileAttributes", wintypes.DWORD), ("ReparseTag", wintypes.DWORD)]

        class FileDispositionInfo(ctypes.Structure):
            _fields_ = [("DeleteFile", wintypes.BOOL)]

        class FileRenameChoice(ctypes.Union):
            _fields_ = [
                ("ReplaceIfExists", wintypes.BYTE),
                ("Flags", wintypes.DWORD),
            ]

        class FileRenameHeader(ctypes.Structure):
            _anonymous_ = ("Choice",)
            _fields_ = [
                ("Choice", FileRenameChoice),
                ("RootDirectory", wintypes.HANDLE),
                ("FileNameLength", wintypes.DWORD),
            ]

        self.UnicodeString = UnicodeString
        self.ObjectAttributes = ObjectAttributes
        self.IoStatusBlock = IoStatusBlock
        self.FileIdInfo = FileIdInfo
        self.FileAttributeTagInfo = FileAttributeTagInfo
        self.FileDispositionInfo = FileDispositionInfo
        self.FileRenameHeader = FileRenameHeader

        self.ntdll.NtCreateFile.argtypes = [
            ctypes.POINTER(wintypes.HANDLE),
            wintypes.ULONG,
            ctypes.POINTER(ObjectAttributes),
            ctypes.POINTER(IoStatusBlock),
            wintypes.LPVOID,
            wintypes.ULONG,
            wintypes.ULONG,
            wintypes.ULONG,
            wintypes.ULONG,
            wintypes.LPVOID,
            wintypes.ULONG,
        ]
        self.ntdll.NtCreateFile.restype = ctypes.c_long
        self.ntdll.RtlNtStatusToDosError.argtypes = [ctypes.c_long]
        self.ntdll.RtlNtStatusToDosError.restype = wintypes.ULONG
        self.ntdll.NtQueryDirectoryFile.argtypes = [
            wintypes.HANDLE,
            wintypes.HANDLE,
            wintypes.LPVOID,
            wintypes.LPVOID,
            ctypes.POINTER(IoStatusBlock),
            wintypes.LPVOID,
            wintypes.ULONG,
            wintypes.ULONG,
            ctypes.c_ubyte,
            ctypes.POINTER(UnicodeString),
            ctypes.c_ubyte,
        ]
        self.ntdll.NtQueryDirectoryFile.restype = ctypes.c_long
        self.kernel32.CreateFileW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.LPVOID,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.HANDLE,
        ]
        self.kernel32.CreateFileW.restype = wintypes.HANDLE
        self.kernel32.GetFileInformationByHandleEx.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            wintypes.LPVOID,
            wintypes.DWORD,
        ]
        self.kernel32.GetFileInformationByHandleEx.restype = wintypes.BOOL
        self.kernel32.SetFileInformationByHandle.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            wintypes.LPVOID,
            wintypes.DWORD,
        ]
        self.kernel32.SetFileInformationByHandle.restype = wintypes.BOOL
        self.kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        self.kernel32.CloseHandle.restype = wintypes.BOOL
        self.kernel32.FlushFileBuffers.argtypes = [wintypes.HANDLE]
        self.kernel32.FlushFileBuffers.restype = wintypes.BOOL

    def _raise_status(self, status: int, context: str) -> None:
        code = int(self.ntdll.RtlNtStatusToDosError(status))
        if code in {2, 3}:
            raise FileNotFoundError(code, context)
        if code in {80, 183}:
            raise FileExistsError(code, context)
        raise OSError(code, f"{context}: {self.ctypes.FormatError(code)}")

    def _raise_last_error(self, context: str) -> None:
        code = self.ctypes.get_last_error()
        raise OSError(code, f"{context}: {self.ctypes.FormatError(code)}")

    def _open_relative(
        self,
        parent: int,
        name: str,
        *,
        directory: bool | None,
        disposition: int,
        access: int,
    ) -> int:
        if name in {"", ".", ".."} or "\\" in name or "/" in name:
            raise ReviewError(f"Unsafe Windows artifact component: {name!r}")
        buffer = self.ctypes.create_unicode_buffer(name)
        encoded_length = len(name.encode("utf-16-le"))
        unicode_name = self.UnicodeString(
            encoded_length,
            encoded_length + 2,
            self.ctypes.cast(buffer, self.wintypes.LPWSTR),
        )
        attributes = self.ObjectAttributes(
            self.ctypes.sizeof(self.ObjectAttributes),
            self.wintypes.HANDLE(parent),
            self.ctypes.pointer(unicode_name),
            self.OBJ_CASE_INSENSITIVE,
            None,
            None,
        )
        io_status = self.IoStatusBlock()
        handle = self.wintypes.HANDLE()
        options = self.FILE_SYNCHRONOUS_IO_NONALERT | self.FILE_OPEN_REPARSE_POINT
        if directory is True:
            options |= self.FILE_DIRECTORY_FILE
        elif directory is False:
            options |= self.FILE_NON_DIRECTORY_FILE
        status = int(
            self.ntdll.NtCreateFile(
                self.ctypes.byref(handle),
                access,
                self.ctypes.byref(attributes),
                self.ctypes.byref(io_status),
                None,
                self.FILE_ATTRIBUTE_NORMAL,
                self.FILE_SHARE_READ | self.FILE_SHARE_WRITE | self.FILE_SHARE_DELETE,
                disposition,
                options,
                None,
                0,
            )
        )
        if status < 0:
            self._raise_status(status, f"NtCreateFile({name})")
        raw_handle = int(handle.value)
        attribute_info = self.FileAttributeTagInfo()
        if not self.kernel32.GetFileInformationByHandleEx(
            self.wintypes.HANDLE(raw_handle),
            self.FILE_ATTRIBUTE_TAG_INFO_CLASS,
            self.ctypes.byref(attribute_info),
            self.ctypes.sizeof(attribute_info),
        ):
            self.kernel32.CloseHandle(self.wintypes.HANDLE(raw_handle))
            self._raise_last_error(f"GetFileInformationByHandleEx({name})")
        if attribute_info.FileAttributes & self.FILE_ATTRIBUTE_REPARSE_POINT:
            self.kernel32.CloseHandle(self.wintypes.HANDLE(raw_handle))
            raise ReviewError(f"Artifact path contains a Windows reparse point: {name}")
        return raw_handle

    def open_absolute_directory(
        self, path: Path, *, create: bool
    ) -> tuple[int, int, str]:
        absolute = Path(os.path.abspath(os.fspath(path)))
        anchor = absolute.anchor
        components = absolute.parts[1:]
        if not anchor or not components:
            raise ReviewError(f"Artifact authority requires a non-root absolute path: {path}")
        root_handle = self.kernel32.CreateFileW(
            anchor,
            self.FILE_LIST_DIRECTORY | self.FILE_READ_ATTRIBUTES | self.SYNCHRONIZE,
            self.FILE_SHARE_READ | self.FILE_SHARE_WRITE | self.FILE_SHARE_DELETE,
            None,
            self.OPEN_EXISTING,
            self.FILE_FLAG_BACKUP_SEMANTICS | self.FILE_FLAG_OPEN_REPARSE_POINT,
            None,
        )
        if int(root_handle) == self.ctypes.c_void_p(-1).value:
            self._raise_last_error(f"CreateFileW({anchor})")
        parent = int(root_handle)
        try:
            for index, name in enumerate(components):
                try:
                    child = self.open_directory(parent, name)
                except FileNotFoundError:
                    if not create:
                        raise
                    child = self.open_directory(parent, name, create=True)
                if index == len(components) - 1:
                    return parent, child, name
                self.close_directory(parent)
                parent = child
        except BaseException:
            self.close_directory(parent)
            raise
        raise AssertionError("artifact authority path had no components")

    def open_directory(
        self,
        parent: int,
        name: str,
        *,
        create: bool = False,
        exclusive: bool = False,
    ) -> int:
        disposition = self.FILE_CREATE if create and exclusive else (
            self.FILE_OPEN_IF if create else self.FILE_OPEN
        )
        try:
            return self._open_relative(
                parent,
                name,
                directory=True,
                disposition=disposition,
                access=self.FILE_LIST_DIRECTORY
                | self.FILE_READ_ATTRIBUTES
                | self.SYNCHRONIZE,
            )
        except OSError as error:
            if getattr(error, "winerror", error.errno) in {2, 3}:
                raise FileNotFoundError(name) from error
            if getattr(error, "winerror", error.errno) in {80, 183}:
                raise FileExistsError(name) from error
            raise

    def close_directory(self, directory: int) -> None:
        if not self.kernel32.CloseHandle(self.wintypes.HANDLE(directory)):
            self._raise_last_error("CloseHandle(directory)")

    def identity(self, directory: int) -> tuple[int, bytes]:
        info = self.FileIdInfo()
        if not self.kernel32.GetFileInformationByHandleEx(
            self.wintypes.HANDLE(directory),
            self.FILE_ID_INFO_CLASS,
            self.ctypes.byref(info),
            self.ctypes.sizeof(info),
        ):
            self._raise_last_error("GetFileInformationByHandleEx(FileIdInfo)")
        return int(info.VolumeSerialNumber), bytes(info.FileId.Identifier)

    def _open_any(self, parent: int, name: str, *, access: int) -> int:
        return self._open_relative(
            parent,
            name,
            directory=None,
            disposition=self.FILE_OPEN,
            access=access | self.FILE_READ_ATTRIBUTES | self.SYNCHRONIZE,
        )

    def entry_kind(self, parent: int, name: str) -> str | None:
        try:
            handle = self._open_any(parent, name, access=self.FILE_READ_ATTRIBUTES)
        except FileNotFoundError:
            return None
        except OSError as error:
            if getattr(error, "winerror", error.errno) in {2, 3}:
                return None
            raise
        try:
            info = self.FileAttributeTagInfo()
            if not self.kernel32.GetFileInformationByHandleEx(
                self.wintypes.HANDLE(handle),
                self.FILE_ATTRIBUTE_TAG_INFO_CLASS,
                self.ctypes.byref(info),
                self.ctypes.sizeof(info),
            ):
                self._raise_last_error("GetFileInformationByHandleEx(FileAttributeTagInfo)")
            if info.FileAttributes & self.FILE_ATTRIBUTE_REPARSE_POINT:
                return "symlink"
            if info.FileAttributes & self.FILE_ATTRIBUTE_DIRECTORY:
                return "directory"
            return "file"
        finally:
            self.close_directory(handle)

    def _descriptor_from_handle(self, handle: int, flags: int) -> int:
        import msvcrt

        return msvcrt.open_osfhandle(handle, flags)

    def read_bytes(self, parent: int, name: str) -> bytes:
        handle = self._open_relative(
            parent,
            name,
            directory=False,
            disposition=self.FILE_OPEN,
            access=self.FILE_READ_DATA | self.FILE_READ_ATTRIBUTES | self.SYNCHRONIZE,
        )
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
        descriptor = self._descriptor_from_handle(handle, flags)
        with os.fdopen(descriptor, "rb") as stream:
            return stream.read()

    def open_lock_descriptor(self, parent: int, name: str) -> int:
        handle = self._open_relative(
            parent,
            name,
            directory=False,
            disposition=self.FILE_OPEN_IF,
            access=self.FILE_READ_DATA
            | self.FILE_WRITE_DATA
            | self.FILE_READ_ATTRIBUTES
            | self.SYNCHRONIZE,
        )
        return self._descriptor_from_handle(
            handle, os.O_RDWR | getattr(os, "O_BINARY", 0)
        )

    def create_temporary(
        self, parent: int, target_name: str, data: bytes
    ) -> _ArtifactTemporary:
        temporary_name = f".{target_name}.{uuid.uuid4().hex}.tmp"
        handle = self._open_relative(
            parent,
            temporary_name,
            directory=False,
            disposition=self.FILE_CREATE,
            access=self.FILE_WRITE_DATA
            | self.FILE_READ_ATTRIBUTES
            | self.DELETE
            | self.SYNCHRONIZE,
        )
        descriptor = self._descriptor_from_handle(
            handle, os.O_WRONLY | getattr(os, "O_BINARY", 0)
        )
        try:
            with os.fdopen(descriptor, "wb", closefd=False) as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
        except BaseException:
            os.close(descriptor)
            raise
        return _ArtifactTemporary(temporary_name, descriptor)

    def replace_temporary(
        self, parent: int, temporary: _ArtifactTemporary, target_name: str
    ) -> None:
        import msvcrt

        handle = int(msvcrt.get_osfhandle(temporary.descriptor))
        encoded_name = target_name.encode("utf-16-le")
        header_size = self.ctypes.sizeof(self.FileRenameHeader)
        buffer = self.ctypes.create_string_buffer(header_size + len(encoded_name))
        header = self.FileRenameHeader.from_buffer(buffer)
        header.ReplaceIfExists = 1
        header.RootDirectory = self.wintypes.HANDLE(parent)
        header.FileNameLength = len(encoded_name)
        self.ctypes.memmove(
            self.ctypes.addressof(buffer) + header_size,
            encoded_name,
            len(encoded_name),
        )
        if not self.kernel32.SetFileInformationByHandle(
            self.wintypes.HANDLE(handle),
            self.FILE_RENAME_INFO_CLASS,
            buffer,
            len(buffer),
        ):
            self._raise_last_error("SetFileInformationByHandle(FileRenameInfo)")

    @staticmethod
    def close_temporary(temporary: _ArtifactTemporary) -> None:
        os.close(temporary.descriptor)

    def cleanup_temporary(self, parent: int, temporary: _ArtifactTemporary) -> None:
        self._delete_named_entry(parent, temporary.name)

    def flush_directory(self, directory: int) -> None:
        self.kernel32.FlushFileBuffers(self.wintypes.HANDLE(directory))

    def list_names(self, directory: int) -> list[str]:
        names: list[str] = []
        restart = True
        while True:
            buffer = self.ctypes.create_string_buffer(64 * 1024)
            io_status = self.IoStatusBlock()
            status = int(
                self.ntdll.NtQueryDirectoryFile(
                    self.wintypes.HANDLE(directory),
                    None,
                    None,
                    None,
                    self.ctypes.byref(io_status),
                    buffer,
                    len(buffer),
                    self.FILE_DIRECTORY_INFORMATION_CLASS,
                    False,
                    None,
                    restart,
                )
            )
            unsigned_status = status & 0xFFFFFFFF
            if unsigned_status == self.STATUS_NO_MORE_FILES:
                break
            if status < 0 and unsigned_status != self.STATUS_BUFFER_OVERFLOW:
                self._raise_status(status, "NtQueryDirectoryFile")
            raw = buffer.raw[: int(io_status.Information)]
            offset = 0
            while offset + 64 <= len(raw):
                next_offset = struct.unpack_from("<I", raw, offset)[0]
                name_length = struct.unpack_from("<I", raw, offset + 60)[0]
                name = raw[offset + 64 : offset + 64 + name_length].decode("utf-16-le")
                if name not in {".", ".."}:
                    names.append(name)
                if next_offset == 0:
                    break
                offset += next_offset
            restart = False
        return sorted(names)

    def _delete_handle(self, handle: int) -> None:
        disposition = self.FileDispositionInfo(True)
        if not self.kernel32.SetFileInformationByHandle(
            self.wintypes.HANDLE(handle),
            self.FILE_DISPOSITION_INFO_CLASS,
            self.ctypes.byref(disposition),
            self.ctypes.sizeof(disposition),
        ):
            self._raise_last_error("SetFileInformationByHandle(FileDispositionInfo)")

    def _delete_named_entry(self, parent: int, name: str) -> None:
        try:
            handle = self._open_any(parent, name, access=self.DELETE)
        except FileNotFoundError:
            return
        try:
            self._delete_handle(handle)
        finally:
            self.close_directory(handle)

    def remove_entry(self, parent: int, name: str, *, recursive: bool) -> None:
        kind = self.entry_kind(parent, name)
        if kind is None:
            return
        if kind == "directory":
            directory = self._open_relative(
                parent,
                name,
                directory=True,
                disposition=self.FILE_OPEN,
                access=self.FILE_LIST_DIRECTORY
                | self.FILE_READ_ATTRIBUTES
                | self.DELETE
                | self.SYNCHRONIZE,
            )
            try:
                names = self.list_names(directory)
                if names and not recursive:
                    raise OSError(f"artifact directory is not empty: {name}")
                for child_name in names:
                    self.remove_entry(directory, child_name, recursive=True)
                self._delete_handle(directory)
            finally:
                self.close_directory(directory)
            return
        self._delete_named_entry(parent, name)

    def rename_entry(self, parent: int, source_name: str, target_name: str) -> None:
        handle = self._open_any(parent, source_name, access=self.DELETE)
        try:
            encoded_name = target_name.encode("utf-16-le")
            header_size = self.ctypes.sizeof(self.FileRenameHeader)
            buffer = self.ctypes.create_string_buffer(header_size + len(encoded_name))
            header = self.FileRenameHeader.from_buffer(buffer)
            header.ReplaceIfExists = 1
            header.RootDirectory = self.wintypes.HANDLE(parent)
            header.FileNameLength = len(encoded_name)
            self.ctypes.memmove(
                self.ctypes.addressof(buffer) + header_size,
                encoded_name,
                len(encoded_name),
            )
            if not self.kernel32.SetFileInformationByHandle(
                self.wintypes.HANDLE(handle),
                self.FILE_RENAME_INFO_CLASS,
                buffer,
                len(buffer),
            ):
                self._raise_last_error("SetFileInformationByHandle(FileRenameInfo)")
        finally:
            self.close_directory(handle)


_ARTIFACT_TEST_HOOK: Any = None


class RunArtifactAuthority:
    """Bind artifact reads and mutations to retained no-follow directory identities."""

    def __init__(self, root_path: Path, *, create: bool = False, backend: Any = None) -> None:
        requested_root = Path(os.path.abspath(os.fspath(root_path)))
        self.root_path = requested_root.resolve(strict=False)
        self._accepted_roots = tuple(dict.fromkeys((requested_root, self.root_path)))
        self.backend = backend or (
            _WindowsArtifactBackend() if os.name == "nt" else _PosixArtifactBackend()
        )
        try:
            self._root_parent, self._root, self._root_name = (
                self.backend.open_absolute_directory(self.root_path, create=create)
            )
        except (FileNotFoundError, NotADirectoryError, OSError) as error:
            raise ReviewError(
                f"Could not establish artifact directory authority for {self.root_path}: {error}"
            ) from error
        self._root_identity = self.backend.identity(self._root)
        self._directories: dict[tuple[str, ...], Any] = {(): self._root}
        self._closed = False

    def _relative_parts(self, path: Path) -> tuple[str, ...] | None:
        absolute = Path(os.path.abspath(os.fspath(path)))
        relative: Path | None = None
        for accepted_root in self._accepted_roots:
            try:
                relative = absolute.relative_to(accepted_root)
                break
            except ValueError:
                continue
        if relative is None:
            return None
        if relative == Path("."):
            return ()
        parts = relative.parts
        if any(part in {"", ".", ".."} for part in parts):
            raise ReviewError(f"Unsafe artifact-relative path: {relative}")
        return parts

    def contains(self, path: Path) -> bool:
        return self._relative_parts(path) is not None

    def _require_parts(self, path: Path) -> tuple[str, ...]:
        parts = self._relative_parts(path)
        if parts is None:
            raise ReviewError(f"Path is outside the active artifact authority: {path}")
        return parts

    def _verify_root(self) -> None:
        try:
            current = self.backend.open_directory(self._root_parent, self._root_name)
        except BaseException as error:
            raise ReviewError(
                "Artifact run name no longer resolves to the retained directory identity"
            ) from error
        try:
            if self.backend.identity(current) != self._root_identity:
                raise ReviewError(
                    "Artifact run name was rebound to a different directory identity"
                )
        finally:
            self.backend.close_directory(current)

    def _directory(
        self, parts: tuple[str, ...], *, create: bool = False
    ) -> Any:
        current_parts: tuple[str, ...] = ()
        current = self._root
        for name in parts:
            next_parts = (*current_parts, name)
            cached = self._directories.get(next_parts)
            if cached is None:
                try:
                    cached = self.backend.open_directory(current, name)
                except FileNotFoundError as error:
                    if not create:
                        raise ReviewError(
                            f"Artifact directory is missing: {'/'.join(next_parts)}"
                        ) from error
                    self.verify_reachable(current_parts)
                    try:
                        cached = self.backend.open_directory(
                            current,
                            name,
                            create=True,
                            exclusive=True,
                        )
                    except FileExistsError:
                        cached = self.backend.open_directory(current, name)
                self._directories[next_parts] = cached
            current_parts = next_parts
            current = cached
        return current

    def verify_reachable(self, parts: tuple[str, ...] = ()) -> None:
        self._verify_root()
        current_parts: tuple[str, ...] = ()
        current = self._root
        for name in parts:
            next_parts = (*current_parts, name)
            retained = self._directories.get(next_parts)
            if retained is None:
                retained = self._directory(next_parts)
            try:
                fresh = self.backend.open_directory(current, name)
            except BaseException as error:
                raise ReviewError(
                    "Artifact descendant no longer resolves to its retained identity: "
                    + "/".join(next_parts)
                ) from error
            try:
                if self.backend.identity(fresh) != self.backend.identity(retained):
                    raise ReviewError(
                        "Artifact descendant was rebound to a different identity: "
                        + "/".join(next_parts)
                    )
            finally:
                self.backend.close_directory(fresh)
            current_parts = next_parts
            current = retained

    def read_bytes(self, path: Path) -> bytes:
        parts = self._require_parts(path)
        if not parts:
            raise ReviewError(f"Cannot read artifact directory as bytes: {path}")
        parent_parts, name = parts[:-1], parts[-1]
        parent = self._directory(parent_parts)
        self.verify_reachable(parent_parts)
        return self.backend.read_bytes(parent, name)

    def entry_kind(self, path: Path) -> str | None:
        parts = self._require_parts(path)
        if not parts:
            return "directory"
        parent_parts, name = parts[:-1], parts[-1]
        try:
            parent = self._directory(parent_parts)
        except ReviewError:
            return None
        self.verify_reachable(parent_parts)
        return self.backend.entry_kind(parent, name)

    def atomic_write_bytes(self, path: Path, data: bytes) -> None:
        parts = self._require_parts(path)
        if not parts:
            raise ReviewError(f"Cannot replace artifact authority root: {path}")
        parent_parts, name = parts[:-1], parts[-1]
        parent = self._directory(parent_parts, create=True)
        self.verify_reachable(parent_parts)
        if _ARTIFACT_TEST_HOOK is not None:
            _ARTIFACT_TEST_HOOK("before_temp_created", self, path)
        temporary = self.backend.create_temporary(parent, name, data)
        replaced = False
        try:
            if _ARTIFACT_TEST_HOOK is not None:
                _ARTIFACT_TEST_HOOK("after_temp_created", self, path)
            self.verify_reachable(parent_parts)
            self.backend.replace_temporary(parent, temporary, name)
            replaced = True
            self.backend.flush_directory(parent)
        finally:
            try:
                self.backend.close_temporary(temporary)
            finally:
                self.backend.cleanup_temporary(parent, temporary)
        try:
            self.verify_reachable(parent_parts)
        except ReviewError as error:
            if replaced:
                raise ReviewError(
                    "Artifact directory was renamed after an identity-bound write; "
                    "a bounded mutation may exist in the retained original directory "
                    "and no pathname rollback was attempted"
                ) from error
            raise

    def open_lock_descriptor(self, path: Path) -> int:
        parts = self._require_parts(path)
        if not parts:
            raise ReviewError("Artifact lock path must name a file")
        parent_parts, name = parts[:-1], parts[-1]
        parent = self._directory(parent_parts, create=True)
        self.verify_reachable(parent_parts)
        return self.backend.open_lock_descriptor(parent, name)

    def mkdir(self, path: Path, *, parents: bool, exist_ok: bool) -> None:
        parts = self._require_parts(path)
        if not parts:
            if exist_ok:
                return
            raise FileExistsError(path)
        if parents:
            if not exist_ok and self.entry_kind(path) is not None:
                raise FileExistsError(path)
            self._directory(parts, create=True)
            self.verify_reachable(parts)
            return
        parent_parts, name = parts[:-1], parts[-1]
        parent = self._directory(parent_parts)
        self.verify_reachable(parent_parts)
        if self.backend.entry_kind(parent, name) is not None:
            if exist_ok and self.backend.entry_kind(parent, name) == "directory":
                self._directory(parts)
                return
            raise FileExistsError(path)
        directory = self.backend.open_directory(
            parent, name, create=True, exclusive=True
        )
        self._directories[parts] = directory
        self.verify_reachable(parts)

    def remove(self, path: Path, *, recursive: bool, missing_ok: bool = False) -> None:
        parts = self._require_parts(path)
        if not parts:
            raise ReviewError("Refusing to remove active artifact authority root")
        parent_parts, name = parts[:-1], parts[-1]
        parent = self._directory(parent_parts)
        self.verify_reachable(parent_parts)
        kind = self.backend.entry_kind(parent, name)
        if kind is None:
            if missing_ok:
                return
            raise FileNotFoundError(path)
        for cached_parts in sorted(
            [item for item in self._directories if item[: len(parts)] == parts],
            key=len,
            reverse=True,
        ):
            directory = self._directories.pop(cached_parts)
            self.backend.close_directory(directory)
        self.backend.remove_entry(parent, name, recursive=recursive)
        self.verify_reachable(parent_parts)

    def rename(self, source: Path, destination: Path) -> None:
        source_parts = self._require_parts(source)
        destination_parts = self._require_parts(destination)
        if not source_parts or source_parts[:-1] != destination_parts[:-1]:
            raise ReviewError("Artifact rename must remain within one retained parent")
        parent_parts = source_parts[:-1]
        parent = self._directory(parent_parts)
        self.verify_reachable(parent_parts)
        self.backend.rename_entry(parent, source_parts[-1], destination_parts[-1])
        remapped: dict[tuple[str, ...], Any] = {}
        for cached_parts in sorted(self._directories, key=len):
            if cached_parts[: len(source_parts)] != source_parts:
                continue
            directory = self._directories.pop(cached_parts)
            remapped[
                (*destination_parts, *cached_parts[len(source_parts) :])
            ] = directory
        self._directories.update(remapped)
        self.verify_reachable(destination_parts)

    def list_names(self, path: Path) -> list[str]:
        parts = self._require_parts(path)
        directory = self._directory(parts)
        self.verify_reachable(parts)
        return self.backend.list_names(directory)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        seen: set[Any] = set()
        for parts in sorted(self._directories, key=len, reverse=True):
            directory = self._directories[parts]
            if directory in seen:
                continue
            seen.add(directory)
            self.backend.close_directory(directory)
        if self._root_parent not in seen:
            self.backend.close_directory(self._root_parent)


_ACTIVE_ARTIFACT_AUTHORITY: RunArtifactAuthority | None = None


@contextmanager
def active_artifact_authority(authority: RunArtifactAuthority) -> Iterator[None]:
    global _ACTIVE_ARTIFACT_AUTHORITY
    if _ACTIVE_ARTIFACT_AUTHORITY is not None:
        raise ReviewError("Nested artifact authorities are not supported")
    _ACTIVE_ARTIFACT_AUTHORITY = authority
    try:
        yield
    finally:
        _ACTIVE_ARTIFACT_AUTHORITY = None
        authority.close()


def _authority_for_path(path: Path) -> RunArtifactAuthority | None:
    authority = _ACTIVE_ARTIFACT_AUTHORITY
    if authority is not None and authority.contains(path):
        return authority
    return None


def _install_active_artifact_authority(authority: RunArtifactAuthority) -> None:
    global _ACTIVE_ARTIFACT_AUTHORITY
    if _ACTIVE_ARTIFACT_AUTHORITY is not None:
        authority.close()
        raise ReviewError("An artifact authority is already active")
    _ACTIVE_ARTIFACT_AUTHORITY = authority


def _close_active_artifact_authority() -> None:
    global _ACTIVE_ARTIFACT_AUTHORITY
    authority = _ACTIVE_ARTIFACT_AUTHORITY
    _ACTIVE_ARTIFACT_AUTHORITY = None
    if authority is not None:
        authority.close()


def artifact_read_bytes(path: Path) -> bytes:
    authority = _authority_for_path(path)
    if authority is not None:
        return authority.read_bytes(path)
    return path.read_bytes()


def artifact_read_text(
    path: Path, *, encoding: str = "utf-8", errors: str = "strict"
) -> str:
    return artifact_read_bytes(path).decode(encoding, errors)


def artifact_entry_kind(path: Path) -> str | None:
    authority = _authority_for_path(path)
    if authority is not None:
        return authority.entry_kind(path)
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    if stat.S_ISLNK(info.st_mode):
        return "symlink"
    if stat.S_ISDIR(info.st_mode):
        return "directory"
    if stat.S_ISREG(info.st_mode):
        return "file"
    return "other"


def artifact_exists(path: Path) -> bool:
    return artifact_entry_kind(path) is not None


def artifact_is_file(path: Path) -> bool:
    return artifact_entry_kind(path) == "file"


def artifact_is_dir(path: Path) -> bool:
    return artifact_entry_kind(path) == "directory"


def artifact_is_symlink(path: Path) -> bool:
    return artifact_entry_kind(path) == "symlink"


def artifact_mkdir(
    path: Path, *, parents: bool = False, exist_ok: bool = False
) -> None:
    authority = _authority_for_path(path)
    if authority is not None:
        authority.mkdir(path, parents=parents, exist_ok=exist_ok)
        return
    path.mkdir(parents=parents, exist_ok=exist_ok)


def artifact_remove(
    path: Path, *, recursive: bool = False, missing_ok: bool = False
) -> None:
    authority = _authority_for_path(path)
    if authority is not None:
        authority.remove(path, recursive=recursive, missing_ok=missing_ok)
        return
    kind = artifact_entry_kind(path)
    if kind is None:
        if missing_ok:
            return
        raise FileNotFoundError(path)
    if kind == "directory":
        if recursive:
            shutil.rmtree(path)
        else:
            path.rmdir()
    else:
        path.unlink()


def artifact_rename(source: Path, destination: Path) -> None:
    authority = _authority_for_path(source)
    if authority is not None and authority.contains(destination):
        authority.rename(source, destination)
        return
    os.replace(source, destination)


def artifact_list_names(path: Path) -> list[str]:
    authority = _authority_for_path(path)
    if authority is not None:
        return authority.list_names(path)
    return sorted(item.name for item in path.iterdir())


def artifact_iterdir(path: Path) -> list[Path]:
    return [path / name for name in artifact_list_names(path)]


def _candidate_lock_is_contended(error: OSError) -> bool:
    return error.errno in {errno.EACCES, errno.EAGAIN}


def _acquire_candidate_lock(descriptor: int) -> None:
    if os.name == "posix":
        import fcntl

        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return
    if os.name == "nt":
        import msvcrt

        os.lseek(descriptor, 0, os.SEEK_SET)
        msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
        return
    raise ReviewError(
        f"Candidate authority locking is unsupported on platform {os.name!r}"
    )


def _release_candidate_lock(descriptor: int) -> None:
    if os.name == "posix":
        import fcntl

        fcntl.flock(descriptor, fcntl.LOCK_UN)
        return
    if os.name == "nt":
        import msvcrt

        os.lseek(descriptor, 0, os.SEEK_SET)
        msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
        return
    raise ReviewError(
        f"Candidate authority locking is unsupported on platform {os.name!r}"
    )


@contextmanager
def candidate_authority_lock(run_dir: Path) -> Iterator[None]:
    """Serialize current-v5 first candidate authority for one stable run."""

    lock_path = run_dir / ".candidate-ingestion.lock"
    authority = _authority_for_path(lock_path)
    if authority is not None:
        descriptor = authority.open_lock_descriptor(lock_path)
    else:
        flags = os.O_CREAT | os.O_RDWR
        if hasattr(os, "O_BINARY"):
            flags |= os.O_BINARY
        descriptor = os.open(lock_path, flags, 0o600)
    acquired = False
    primary_error: BaseException | None = None
    try:
        if os.name == "nt" and os.fstat(descriptor).st_size == 0:
            os.write(descriptor, b"\0")
            os.fsync(descriptor)
        deadline = time.monotonic() + CANDIDATE_AUTHORITY_LOCK_TIMEOUT_SECONDS
        while True:
            try:
                _acquire_candidate_lock(descriptor)
            except OSError as error:
                if not _candidate_lock_is_contended(error):
                    raise ReviewError(
                        f"Could not acquire candidate authority lock: {error}"
                    ) from error
                if time.monotonic() >= deadline:
                    raise ReviewError(
                        "Timed out acquiring candidate authority lock; no candidate "
                        "authority was published by this attempt"
                    ) from error
                time.sleep(
                    min(
                        CANDIDATE_AUTHORITY_LOCK_POLL_SECONDS,
                        max(0.0, deadline - time.monotonic()),
                    )
                )
                continue
            acquired = True
            break
        yield
    except BaseException as error:
        primary_error = error
        raise
    finally:
        release_error: BaseException | None = None
        if acquired:
            try:
                _release_candidate_lock(descriptor)
            except BaseException as error:
                release_error = error
        try:
            os.close(descriptor)
        except BaseException as error:
            if release_error is None:
                release_error = error
        if release_error is not None:
            if primary_error is not None:
                try:
                    setattr(
                        primary_error,
                        "candidate_lock_release_error",
                        repr(release_error),
                    )
                except BaseException:
                    pass
            else:
                raise ReviewError(
                    f"Candidate authority committed but lock release failed: {release_error}"
                ) from release_error


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        digest.update(artifact_read_bytes(path))
    except FileNotFoundError as exc:
        raise ReviewError(f"Expected artifact file is missing: {path}") from exc
    except OSError as exc:
        raise ReviewError(f"Could not read artifact file {path}: {exc}") from exc
    return digest.hexdigest()


def atomic_write_bytes(path: Path, data: bytes) -> None:
    authority = _authority_for_path(path)
    if authority is not None:
        authority.atomic_write_bytes(path, data)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass


def atomic_write_text(path: Path, text: str) -> None:
    atomic_write_bytes(path, text.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8"))


def atomic_write_json(path: Path, value: Any) -> None:
    atomic_write_text(path, json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n")


def load_json(path: Path) -> Any:
    try:
        return json.loads(artifact_read_text(path, encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ReviewError(f"File not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ReviewError(f"Invalid JSON in {path}: {exc}") from exc


def verify_embedded_hash(
    obj: dict[str, Any],
    *,
    hash_field: str,
    context: str,
    unhashed_fields: Iterable[str] = (),
) -> str:
    """Recompute a persisted artifact hash after removing metadata added later."""
    expected = require_string(obj.get(hash_field), f"{context}.{hash_field}")
    payload = copy.deepcopy(obj)
    payload.pop(hash_field, None)
    for field in unhashed_fields:
        payload.pop(field, None)
    actual = canonical_hash(payload)
    if actual != expected:
        raise ReviewError(
            f"{context} failed its embedded hash check: expected {expected}, recomputed {actual}"
        )
    return expected


def require_state_hash(state: dict[str, Any], key: str, actual: str, context: str) -> None:
    expected = state.get("hashes", {}).get(key)
    if expected != actual:
        raise ReviewError(
            f"{context} does not match state.{key}: state has {expected!r}, artifact has {actual!r}"
        )


def require_state_gate(state: dict[str, Any], key: str, actual: str, context: str) -> None:
    expected = state.get("gates", {}).get(key)
    if expected != actual:
        raise ReviewError(
            f"{context} does not match the recorded {key} gate: state has {expected!r}, artifact has {actual!r}"
        )


def scope_identity_hash(identity: dict[str, Any]) -> str:
    """Hash only review identity, excluding local snapshot storage pointers."""
    payload = copy.deepcopy(identity)
    for entry in payload.get("files", []):
        if not isinstance(entry, dict):
            continue
        for key in ("baseline_state", "comparison_state"):
            state_info = entry.get(key)
            if isinstance(state_info, dict):
                state_info.pop("snapshot_path", None)
    return canonical_hash(payload)


def run_process(
    args: Sequence[str],
    *,
    cwd: Path,
    check: bool = True,
    timeout: int | None = None,
    input_bytes: bytes | None = None,
) -> subprocess.CompletedProcess[bytes]:
    try:
        result = subprocess.run(
            list(args),
            cwd=str(cwd),
            input=input_bytes,
            capture_output=True,
            check=False,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        raise ReviewError(f"Executable not found: {args[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise ReviewError(f"Command timed out after {timeout}s: {' '.join(args)}") from exc
    if check and result.returncode != 0:
        stderr = result.stderr.decode("utf-8", errors="replace").strip()
        stdout = result.stdout.decode("utf-8", errors="replace").strip()
        detail = stderr or stdout or f"exit {result.returncode}"
        raise ReviewError(f"Command failed ({' '.join(args)}): {detail}")
    return result


def git_bytes(repo: Path, *args: str, check: bool = True) -> bytes:
    return run_process(["git", *args], cwd=repo, check=check).stdout


def git_text(repo: Path, *args: str, check: bool = True) -> str:
    return git_bytes(repo, *args, check=check).decode("utf-8", errors="surrogateescape").strip()


def resolve_repo_root(raw: str | Path) -> Path:
    candidate = Path(raw).expanduser().resolve()
    result = run_process(["git", "rev-parse", "--show-toplevel"], cwd=candidate, check=True)
    return Path(result.stdout.decode("utf-8", errors="replace").strip()).resolve()


def default_artifact_root(repo: Path) -> Path:
    raw = git_text(repo, "rev-parse", "--git-path", "material-code-review")
    path = Path(raw)
    if not path.is_absolute():
        path = repo / path
    return path.resolve()


def resolve_artifact_root(repo: Path, raw: str | None) -> Path:
    artifact_root = Path(raw).expanduser().resolve() if raw else default_artifact_root(repo)
    git_dir = Path(git_text(repo, "rev-parse", "--absolute-git-dir")).resolve()
    if artifact_root.is_relative_to(repo) and not artifact_root.is_relative_to(git_dir):
        raise ReviewError(
            "Artifact storage may not be inside the working tree. Use the default Git-path storage or an external path."
        )
    return artifact_root


def normalize_run_id(raw: str) -> str:
    value = require_string(raw, "run ID")
    if value in {".", ".."} or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", value):
        raise ReviewError(
            "Run ID must be 1-128 characters using letters, digits, dot, underscore, or hyphen, and may not traverse paths"
        )
    return value


def normalize_repo_path(raw: str, *, allow_dot: bool = False) -> str:
    value = raw.replace("\\", "/").strip()
    if allow_dot and value in {"", ".", "./"}:
        return "."
    while value.startswith("./"):
        value = value[2:]
    if not value or value.startswith("/") or re.match(r"^[A-Za-z]:/", value):
        raise ReviewError(f"Path must be repository-relative: {raw!r}")
    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ReviewError(f"Path contains an unsafe component: {raw!r}")
    if parts[0] == ".git":
        raise ReviewError(f"Path may not target .git: {raw!r}")
    return "/".join(parts)


def require_canonical_repo_path(raw: Any, context: str) -> str:
    if not isinstance(raw, str):
        raise ReviewError(f"{context} must be a string")
    if "\0" in raw or re.match(r"^[A-Za-z]:", raw):
        raise ReviewError(
            f"{context} must be a canonical repository-relative forward-slash Git path: {raw!r}"
        )
    try:
        normalized = normalize_repo_path(raw)
    except ReviewError as exc:
        raise ReviewError(
            f"{context} must be a canonical repository-relative forward-slash Git path: {raw!r}"
        ) from exc
    if raw != normalized or raw[:1] == "\ufeff" or raw[-1:] == "\ufeff":
        raise ReviewError(
            f"{context} must be a canonical repository-relative forward-slash Git path: {raw!r}"
        )
    return raw


def require_canonical_repo_path_array(value: Any, context: str) -> list[str]:
    values = require_array(value, context)
    result = [
        require_canonical_repo_path(item, f"{context}[{index}]")
        for index, item in enumerate(values)
    ]
    if len(set(result)) != len(result):
        raise ReviewError(f"{context} must contain unique values")
    return result


def repo_path(repo: Path, relative: str) -> Path:
    normalized = normalize_repo_path(relative)
    # Canonicalize the repository root before containment checks. On macOS,
    # temporary paths may be exposed as /var/... while resolving a parent
    # produces /private/var/.... Comparing those aliases directly causes a
    # valid in-repository path to be rejected as an escape.
    canonical_repo = repo.resolve(strict=True)
    target = canonical_repo / normalized
    # Resolve the parent, not the final component. Resolving the final
    # component would follow a repository symlink and make checkpoint logic
    # operate on its target rather than on the symlink itself.
    resolved_parent = target.parent.resolve(strict=False)
    try:
        resolved_parent.relative_to(canonical_repo)
    except ValueError as exc:
        raise ReviewError(f"Path escapes repository through a parent symlink: {relative}") from exc
    return target


def require_object(value: Any, context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ReviewError(f"{context} must be a JSON object")
    return value


def require_array(value: Any, context: str) -> list[Any]:
    if not isinstance(value, list):
        raise ReviewError(f"{context} must be an array")
    return value


def require_string(value: Any, context: str, *, nonempty: bool = True) -> str:
    if not isinstance(value, str):
        raise ReviewError(f"{context} must be a string")
    if nonempty and not value.strip():
        raise ReviewError(f"{context} must not be empty")
    return value


def require_sha256(value: Any, context: str) -> str:
    digest = require_string(value, context)
    if re.fullmatch(r"[0-9a-f]{64}", digest) is None:
        raise ReviewError(f"{context} must be a lowercase SHA-256 digest")
    return digest


def require_bool(value: Any, context: str) -> bool:
    if not isinstance(value, bool):
        raise ReviewError(f"{context} must be a boolean")
    return value


def is_current_material_review_state(state: dict[str, Any]) -> bool:
    return (
        state.get("schema_version") == MATERIAL_REVIEW_STATE_SCHEMA
        and state.get("workflow_profile") == WORKFLOW_PROFILE_REVIEW
        and state.get("coverage_required") is True
        and "profile" not in state
    )


def classify_state_contract(
    state: dict[str, Any], *, run_dir: Path | None = None
) -> str:
    schema_version = state.get("schema_version")
    profile = state.get("profile")
    profile_present = "profile" in state
    coverage_required = state.get("coverage_required")
    workflow_profile = state.get("workflow_profile")

    if is_current_material_review_state(state):
        return STATE_CONTRACT_MATERIAL_REVIEW
    if (
        schema_version == SIMPLIFICATION_STATE_SCHEMA
        and profile == SIMPLIFICATION_PROFILE
        and "coverage_required" not in state
        and "workflow_profile" not in state
    ):
        return STATE_CONTRACT_SIMPLIFICATION
    if (
        schema_version == LEGACY_MATERIAL_REVIEW_STATE_SCHEMA_V5
        and not profile_present
        and coverage_required is True
        and workflow_profile == WORKFLOW_PROFILE_REVIEW
    ):
        return STATE_CONTRACT_LEGACY_MATERIAL_REVIEW_V5
    if (
        schema_version == LEGACY_MATERIAL_REVIEW_STATE_SCHEMA_V4
        and not profile_present
        and coverage_required is True
        and workflow_profile == WORKFLOW_PROFILE_REVIEW
    ):
        return STATE_CONTRACT_LEGACY_MATERIAL_REVIEW_V4
    if (
        schema_version == LEGACY_MATERIAL_REVIEW_STATE_SCHEMA_V3
        and not profile_present
        and coverage_required is True
        and workflow_profile == WORKFLOW_PROFILE_REVIEW
    ):
        return STATE_CONTRACT_LEGACY_MATERIAL_REVIEW_V3
    if (
        schema_version == LEGACY_MATERIAL_REVIEW_STATE_SCHEMA_V2
        and not profile_present
        and coverage_required is True
        and workflow_profile == WORKFLOW_PROFILE_REVIEW
    ):
        return STATE_CONTRACT_FINALIZABLE_MATERIAL_REVIEW_V2
    if (
        schema_version == LEGACY_MATERIAL_REVIEW_STATE_SCHEMA_V1
        and not profile_present
        and coverage_required is True
        and workflow_profile == WORKFLOW_PROFILE_REVIEW
    ):
        return STATE_CONTRACT_FINALIZABLE_MATERIAL_REVIEW_V1
    if (
        schema_version == LEGACY_MATERIAL_REVIEW_STATE_SCHEMA_V1
        and not profile_present
        and "coverage_required" not in state
        and "workflow_profile" not in state
    ):
        return STATE_CONTRACT_LEGACY_MATERIAL_REVIEW

    location = f" in {run_dir}" if run_dir is not None else ""
    raise ReviewError(f"Unsupported or contradictory state identity{location}")


def is_simplification_state(state: dict[str, Any]) -> bool:
    return classify_state_contract(state) == STATE_CONTRACT_SIMPLIFICATION


def expected_normalized_candidates_schema(state: dict[str, Any]) -> str:
    contract = classify_state_contract(state)
    if contract == STATE_CONTRACT_MATERIAL_REVIEW:
        return NORMALIZED_CANDIDATES_SCHEMA_REVIEW
    if contract == STATE_CONTRACT_SIMPLIFICATION:
        return NORMALIZED_CANDIDATES_SCHEMA_SIMPLIFICATION
    raise ReviewError("Run predates required coverage; start a new run.")


def expected_adjudication_schema(state: dict[str, Any]) -> str:
    contract = classify_state_contract(state)
    if contract == STATE_CONTRACT_MATERIAL_REVIEW:
        return ADJUDICATION_SCHEMA_REVIEW
    if contract == STATE_CONTRACT_SIMPLIFICATION:
        return ADJUDICATION_SCHEMA_SIMPLIFICATION
    raise ReviewError("Run predates required coverage; start a new run.")


def expected_ledger_schema(state: dict[str, Any]) -> str:
    contract = classify_state_contract(state)
    if contract == STATE_CONTRACT_MATERIAL_REVIEW:
        return LEDGER_SCHEMA_REVIEW
    if contract == STATE_CONTRACT_SIMPLIFICATION:
        return LEDGER_SCHEMA_SIMPLIFICATION
    raise ReviewError("Run predates required coverage; start a new run.")


LEGACY_OBSERVATION_COMMANDS = frozenset({"status", "check-scope"})
LEGACY_RESTORATION_COMMANDS = frozenset({"rollback-finding", "abort-fixes"})
LEGACY_ALLOWED_COMMANDS = LEGACY_OBSERVATION_COMMANDS | LEGACY_RESTORATION_COMMANDS
def enforce_command_compatibility(args: argparse.Namespace) -> None:
    if args.command == "init":
        return
    workflow_profile = getattr(args, "_workflow_profile", None)
    if workflow_profile not in {WORKFLOW_PROFILE_REVIEW, SIMPLIFICATION_PROFILE}:
        raise ReviewError("Controller caller has no valid workflow profile")
    repo = resolve_repo_root(args.repo_root)
    _, run_dir = resolve_run_dir(args, repo)
    state = load_state(run_dir)
    contract = classify_state_contract(state, run_dir=run_dir)
    if workflow_profile == SIMPLIFICATION_PROFILE:
        if contract != STATE_CONTRACT_SIMPLIFICATION:
            raise ReviewError(
                "Run workflow profile does not match the material-code-simplification entrypoint"
            )
        return
    if contract == STATE_CONTRACT_SIMPLIFICATION:
        raise ReviewError(
            "Run workflow profile does not match the material-review entrypoint"
        )
    if contract == STATE_CONTRACT_MATERIAL_REVIEW:
        return
    if (
        contract
        in {
            STATE_CONTRACT_LEGACY_MATERIAL_REVIEW_V4,
            STATE_CONTRACT_LEGACY_MATERIAL_REVIEW_V5,
            STATE_CONTRACT_LEGACY_MATERIAL_REVIEW_V3,
            STATE_CONTRACT_FINALIZABLE_MATERIAL_REVIEW_V1,
            STATE_CONTRACT_FINALIZABLE_MATERIAL_REVIEW_V2,
        }
        and args.command in LEGACY_ALLOWED_COMMANDS
    ):
        return
    if args.command not in LEGACY_ALLOWED_COMMANDS:
        raise ReviewError("Run predates required coverage; start a new run.")


def require_current_material_review_contract(state: dict[str, Any]) -> None:
    contract = classify_state_contract(state)
    if contract == STATE_CONTRACT_SIMPLIFICATION:
        raise ReviewError("Material-review coverage is not used for material simplification")
    if contract != STATE_CONTRACT_MATERIAL_REVIEW:
        raise ReviewError("Run predates required coverage; start a new run.")


def require_int(value: Any, context: str, *, minimum: int | None = None, maximum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ReviewError(f"{context} must be an integer")
    if minimum is not None and value < minimum:
        raise ReviewError(f"{context} must be >= {minimum}")
    if maximum is not None and value > maximum:
        raise ReviewError(f"{context} must be <= {maximum}")
    return value


def require_exact_keys(obj: dict[str, Any], expected: set[str], context: str) -> None:
    actual = set(obj)
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    if missing or extra:
        details: list[str] = []
        if missing:
            details.append(f"missing {', '.join(missing)}")
        if extra:
            details.append(f"unexpected {', '.join(extra)}")
        raise ReviewError(f"{context} has invalid fields: {'; '.join(details)}")


def require_string_array(value: Any, context: str, *, unique: bool = True) -> list[str]:
    values = require_array(value, context)
    result = [require_string(item, f"{context}[{index}]") for index, item in enumerate(values)]
    if unique and len(set(result)) != len(result):
        raise ReviewError(f"{context} must contain unique values")
    return result


def parse_csv_ids(values: Sequence[str] | None) -> set[str]:
    result: set[str] = set()
    for raw in values or []:
        for item in raw.split(","):
            item = item.strip()
            if item:
                result.add(item)
    return result


def path_state(path: Path) -> dict[str, Any]:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return {"type": "missing"}
    mode = stat.S_IMODE(info.st_mode)
    if stat.S_ISLNK(info.st_mode):
        target = os.readlink(path)
        data = os.fsencode(target)
        return {"type": "symlink", "target": target, "mode": mode, "sha256": sha256_bytes(data), "size": len(data)}
    if stat.S_ISREG(info.st_mode):
        return {"type": "file", "mode": mode, "sha256": sha256_file(path), "size": info.st_size}
    if stat.S_ISDIR(info.st_mode):
        return {"type": "directory", "mode": mode}
    return {"type": "other", "mode": mode, "size": info.st_size}


def bytes_are_binary(data: bytes) -> bool:
    if b"\x00" in data[:8192]:
        return True
    try:
        data.decode("utf-8")
        return False
    except UnicodeDecodeError:
        return True


def git_object_bytes(repo: Path, commit: str, path: str) -> bytes | None:
    result = run_process(["git", "show", f"{commit}:{path}"], cwd=repo, check=False)
    if result.returncode != 0:
        return None
    return result.stdout


def source_state_from_bytes(data: bytes | None) -> dict[str, Any]:
    if data is None:
        return {"type": "missing"}
    return {
        "type": "file",
        "sha256": sha256_bytes(data),
        "size": len(data),
        "binary": bytes_are_binary(data),
    }


def parse_name_status_z(data: bytes) -> list[dict[str, Any]]:
    tokens = data.split(b"\0")
    entries: list[dict[str, Any]] = []
    index = 0
    while index < len(tokens):
        status_raw = tokens[index]
        index += 1
        if not status_raw:
            continue
        status = status_raw.decode("ascii", errors="replace")
        if index >= len(tokens):
            raise ReviewError("Malformed git --name-status -z output")
        first = os.fsdecode(tokens[index])
        index += 1
        code = status[:1]
        if code in {"R", "C"}:
            if index >= len(tokens):
                raise ReviewError("Malformed rename/copy record in git diff")
            second = os.fsdecode(tokens[index])
            index += 1
            entries.append({"status": status, "old_path": first, "path": second, "tracked": True})
        else:
            entries.append({"status": status, "old_path": None, "path": first, "tracked": True})
    return entries


def parse_status_paths_z(data: bytes) -> set[str]:
    tokens = data.split(b"\0")
    paths: set[str] = set()
    index = 0
    while index < len(tokens):
        record = tokens[index]
        index += 1
        if not record:
            continue
        if len(record) < 3:
            raise ReviewError("Malformed git status --porcelain -z output")
        xy = record[:2].decode("ascii", errors="replace")
        path = os.fsdecode(record[3:])
        paths.add(normalize_repo_path(path))
        if "R" in xy or "C" in xy:
            if index >= len(tokens):
                raise ReviewError("Malformed rename/copy record in git status")
            other = os.fsdecode(tokens[index])
            index += 1
            if other:
                paths.add(normalize_repo_path(other))
    return paths


def current_branch(repo: Path) -> str:
    result = run_process(["git", "symbolic-ref", "--quiet", "--short", "HEAD"], cwd=repo, check=False)
    if result.returncode != 0:
        return "DETACHED"
    return result.stdout.decode("utf-8", errors="replace").strip()


def current_head_attachment(repo: Path) -> str | None:
    result = run_process(
        ["git", "symbolic-ref", "--quiet", "HEAD"], cwd=repo, check=False
    )
    if result.returncode != 0:
        return None
    ref = result.stdout.decode("utf-8", errors="replace").strip()
    if not ref.startswith("refs/heads/") or ref == "refs/heads/":
        raise ReviewError(f"HEAD has an unsupported symbolic target: {ref!r}")
    return ref


def local_head_refs(repo: Path) -> dict[str, str]:
    return {
        ref: object_id
        for ref, object_id in repository_refs(repo).items()
        if ref.startswith("refs/heads/")
    }


def repository_refs(repo: Path) -> dict[str, str]:
    raw = git_text(
        repo,
        "for-each-ref",
        "--format=%(refname)%00%(objectname)",
        "refs",
    )
    refs: dict[str, str] = {}
    for line in raw.splitlines():
        if not line:
            continue
        parts = line.split("\x00")
        if len(parts) != 2:
            raise ReviewError("Git returned malformed local branch-ref data")
        ref, object_id = parts
        if (
            not ref.startswith("refs/")
            or ref == "refs/"
            or re.fullmatch(r"[0-9a-f]{40,64}", object_id) is None
            or ref in refs
        ):
            raise ReviewError("Git returned invalid ref data")
        refs[ref] = object_id
    return dict(sorted(refs.items()))


def resolve_commit(repo: Path, ref: str) -> str:
    return git_text(repo, "rev-parse", "--verify", f"{ref}^{{commit}}")


def detect_default_base(repo: Path) -> str:
    candidates: list[str] = []
    symbolic = run_process(
        ["git", "symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD"],
        cwd=repo,
        check=False,
    )
    if symbolic.returncode == 0:
        value = symbolic.stdout.decode("utf-8", errors="replace").strip()
        if value:
            candidates.append(value)
    candidates.extend(["origin/main", "origin/master", "main", "master"])
    seen: set[str] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        result = run_process(["git", "rev-parse", "--verify", f"{candidate}^{{commit}}"], cwd=repo, check=False)
        if result.returncode == 0:
            return candidate
    raise ReviewError("Could not resolve a default base branch. Pass --base <ref> explicitly.")


def workspace_has_changes(repo: Path, *, include_untracked: bool) -> bool:
    tracked = git_bytes(repo, "status", "--porcelain=v1", "-z", "--untracked-files=no")
    if tracked:
        return True
    if include_untracked:
        return bool(git_bytes(repo, "ls-files", "--others", "--exclude-standard", "-z"))
    return False


def diff_args_for_scope(scope: dict[str, Any], *, name_status: bool = False) -> list[str]:
    base = scope["baseline_sha"]
    if name_status:
        prefix = ["diff", "--name-status", "-z", "--find-renames"]
    else:
        prefix = ["diff", "--binary", "--full-index", "--find-renames"]
    if scope["comparison_kind"] == "working-tree":
        return [*prefix, base, "--"]
    return [*prefix, f"{base}..{scope['comparison_sha']}", "--"]


def build_scope(
    repo: Path,
    *,
    requested_scope: str,
    base_ref: str | None,
    head_ref: str | None,
    include_untracked: bool,
) -> dict[str, Any]:
    head_sha = resolve_commit(repo, "HEAD")
    branch = current_branch(repo)
    actual_scope = requested_scope
    if requested_scope == "auto":
        actual_scope = "uncommitted" if workspace_has_changes(repo, include_untracked=include_untracked) else "branch"

    if actual_scope == "uncommitted":
        baseline_reference = "HEAD"
        baseline_sha = head_sha
        comparison_kind = "working-tree"
        comparison_reference = "working-tree"
        comparison_sha = head_sha
        mutable = True
    elif actual_scope == "branch":
        baseline_reference = base_ref or detect_default_base(repo)
        resolve_commit(repo, baseline_reference)
        baseline_sha = git_text(repo, "merge-base", "HEAD", baseline_reference)
        comparison_kind = "working-tree"
        comparison_reference = "working-tree"
        comparison_sha = head_sha
        mutable = True
    elif actual_scope == "range":
        if not base_ref or not head_ref:
            raise ReviewError("scope=range requires both --base and --head")
        baseline_reference = base_ref
        comparison_reference = head_ref
        baseline_sha = resolve_commit(repo, base_ref)
        comparison_sha = resolve_commit(repo, head_ref)
        comparison_kind = "commit"
        mutable = False
    else:
        raise ReviewError(f"Unsupported scope: {actual_scope}")

    scope_base: dict[str, Any] = {
        "requested_scope": requested_scope,
        "actual_scope": actual_scope,
        "base_reference": baseline_reference,
        "head_reference": head_ref,
        "baseline_sha": baseline_sha,
        "comparison_kind": comparison_kind,
        "comparison_reference": comparison_reference,
        "comparison_sha": comparison_sha,
        "include_untracked": include_untracked,
        "mutable": mutable,
        "branch": branch if mutable else None,
        "workspace_head_sha": head_sha if mutable else None,
    }

    patch = git_bytes(repo, *diff_args_for_scope(scope_base, name_status=False))
    status_data = git_bytes(repo, *diff_args_for_scope(scope_base, name_status=True))
    entries = parse_name_status_z(status_data)

    if include_untracked and comparison_kind == "working-tree":
        untracked = git_bytes(repo, "ls-files", "--others", "--exclude-standard", "-z")
        for raw in untracked.split(b"\0"):
            if not raw:
                continue
            untracked_path = normalize_repo_path(os.fsdecode(raw))
            if is_transient_runtime_path(untracked_path):
                continue
            entries.append({"status": "U", "old_path": None, "path": untracked_path, "tracked": False})

    normalized_entries: list[dict[str, Any]] = []
    for entry in entries:
        path = normalize_repo_path(entry["path"])
        old_path = normalize_repo_path(entry["old_path"]) if entry.get("old_path") else None
        baseline_path = old_path if old_path is not None else path
        baseline_data = git_object_bytes(repo, baseline_sha, baseline_path)
        if comparison_kind == "commit":
            comparison_data = git_object_bytes(repo, comparison_sha, path)
        else:
            target = repo_path(repo, path)
            if target.is_file() and not target.is_symlink():
                comparison_data = target.read_bytes()
            elif target.is_symlink():
                comparison_data = os.fsencode(os.readlink(target))
            else:
                comparison_data = None
        normalized_entries.append(
            {
                "status": entry["status"],
                "path": path,
                "old_path": old_path,
                "tracked": bool(entry["tracked"]),
                "baseline_state": source_state_from_bytes(baseline_data),
                "comparison_state": source_state_from_bytes(comparison_data),
            }
        )

    normalized_entries.sort(key=lambda item: (item["path"], item.get("old_path") or "", item["status"]))

    if comparison_kind == "working-tree":
        staged_patch = git_bytes(repo, "diff", "--cached", "--binary", "--full-index", baseline_sha, "--")
        unstaged_patch = git_bytes(repo, "diff", "--binary", "--full-index", "--")
    else:
        staged_patch = b""
        unstaged_patch = b""

    identity = {
        "schema_version": SCOPE_SCHEMA,
        "actual_scope": actual_scope,
        "base_reference": baseline_reference,
        "head_reference": head_ref,
        "baseline_sha": baseline_sha,
        "comparison_kind": comparison_kind,
        "comparison_reference": comparison_reference,
        "comparison_sha": comparison_sha,
        "include_untracked": include_untracked,
        "mutable": mutable,
        "branch": branch if mutable else None,
        "workspace_head_sha": head_sha if mutable else None,
        "patch_sha256": sha256_bytes(patch),
        "staged_patch_sha256": sha256_bytes(staged_patch),
        "unstaged_patch_sha256": sha256_bytes(unstaged_patch),
        "files": normalized_entries,
    }
    if not normalized_entries:
        raise ReviewError("The resolved review scope contains no changed files")

    return {
        "identity": identity,
        "scope_hash": scope_identity_hash(identity),
        "patch": patch,
        "staged_patch": staged_patch,
        "unstaged_patch": unstaged_patch,
    }


def all_scope_paths(scope_identity: dict[str, Any]) -> set[str]:
    result: set[str] = set()
    for entry in scope_identity["files"]:
        result.add(entry["path"])
        if entry.get("old_path"):
            result.add(entry["old_path"])
    return result


def collect_coverage_context_paths(plan: dict[str, Any]) -> set[str]:
    paths: set[str] = set()
    for raw_unit in plan.get("change_units", []):
        if not isinstance(raw_unit, dict):
            continue
        for raw_path in raw_unit.get("context_paths", []):
            if isinstance(raw_path, str):
                paths.add(raw_path)
    return paths


def _git_tree_regular_paths(repo: Path, commit: str) -> set[str]:
    paths: set[str] = set()
    for record in git_bytes(repo, "ls-tree", "-r", "-z", "--full-tree", commit).split(b"\0"):
        if not record:
            continue
        try:
            metadata, raw_path = record.split(b"\t", 1)
            mode, object_type, _ = metadata.split(b" ", 2)
            path = os.fsdecode(raw_path)
            if object_type != b"blob" or mode not in {b"100644", b"100755"}:
                continue
            paths.add(canonical_git_path(path, "comparison-tree path"))
        except (ValueError, ObligationContractError):
            continue
    return paths


def discover_comparison_context_paths(
    repo: Path, scope_identity: dict[str, Any]
) -> set[str]:
    if scope_identity["comparison_kind"] == "commit":
        return _git_tree_regular_paths(repo, scope_identity["comparison_sha"])

    paths: set[str] = set()
    for raw_path in git_bytes(repo, "ls-files", "-z").split(b"\0"):
        if not raw_path:
            continue
        try:
            path = canonical_git_path(os.fsdecode(raw_path), "tracked context path")
            target = repo_path(repo, path)
            info = target.lstat()
        except (FileNotFoundError, OSError, ObligationContractError, ReviewError):
            continue
        if stat.S_ISREG(info.st_mode) and not stat.S_ISLNK(info.st_mode):
            paths.add(path)
    return paths


def _read_comparison_context_source(
    repo: Path, scope_identity: dict[str, Any], path: str
) -> bytes:
    if scope_identity["comparison_kind"] == "commit":
        commit = scope_identity["comparison_sha"]
        tree = git_bytes(repo, "ls-tree", "-z", commit, "--", path)
        records = [record for record in tree.split(b"\0") if record]
        if len(records) != 1:
            raise ReviewError(f"Context path is missing from the comparison tree: {path}")
        try:
            metadata, raw_tree_path = records[0].split(b"\t", 1)
            mode, object_type, _ = metadata.split(b" ", 2)
        except ValueError as exc:
            raise ReviewError(f"Malformed Git tree entry for context path: {path}") from exc
        if os.fsdecode(raw_tree_path) != path or object_type != b"blob" or mode not in {b"100644", b"100755"}:
            raise ReviewError(f"Context path is not a tracked regular file in the comparison tree: {path}")
        data = git_object_bytes(repo, commit, path)
        if data is None:
            raise ReviewError(f"Could not freeze comparison-tree context path: {path}")
        return data

    tracked = run_process(
        ["git", "ls-files", "--error-unmatch", "--", path],
        cwd=repo,
        check=False,
    )
    if tracked.returncode != 0:
        raise ReviewError(f"Context path is not tracked in the comparison worktree: {path}")
    target = repo_path(repo, path)
    try:
        info = target.lstat()
    except OSError as exc:
        raise ReviewError(f"Could not inspect context path {path}: {exc}") from exc
    if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
        raise ReviewError(f"Context path is not a regular non-symlink file: {path}")
    try:
        return target.read_bytes()
    except OSError as exc:
        raise ReviewError(f"Could not freeze context path {path}: {exc}") from exc


def _build_coverage_context(
    repo: Path,
    run_dir: Path,
    scope_identity: dict[str, Any],
    context_paths: set[str],
    *,
    max_files: int,
    max_file_bytes: int,
    max_total_bytes: int,
) -> tuple[dict[str, Any], dict[str, bytes]]:
    canonical_paths = sorted(
        canonical_git_path(path, "coverage context path") for path in context_paths
    )
    if len(canonical_paths) > max_files:
        raise ReviewError(f"Coverage context may contain at most {max_files} files")
    if scope_identity["comparison_kind"] == "working-tree":
        check_scope_fresh(repo, run_dir, load_state(run_dir))

    sources: list[dict[str, Any]] = []
    source_bytes: dict[str, bytes] = {}
    total_bytes = 0
    for path in canonical_paths:
        data = _read_comparison_context_source(repo, scope_identity, path)
        if len(data) > max_file_bytes:
            raise ReviewError(
                f"Coverage context file {path} exceeds the 2 MiB per-file limit"
            )
        total_bytes += len(data)
        if total_bytes > max_total_bytes:
            raise ReviewError("Coverage context exceeds the 25 MiB total limit")
        source_bytes[path] = data
        sources.append(
            {
                "path": path,
                "sha256": sha256_bytes(data),
                "size": len(data),
                "snapshot_path": f"coverage-context/sources/{path}",
            }
        )

    if scope_identity["comparison_kind"] == "working-tree":
        check_scope_fresh(repo, run_dir, load_state(run_dir))
    context = {
        "schema_version": COVERAGE_CONTEXT_SCHEMA,
        "scope_hash": scope_identity_hash(scope_identity),
        "comparison_kind": scope_identity["comparison_kind"],
        "comparison_sha": scope_identity["comparison_sha"],
        "sources": sources,
    }
    return context, source_bytes


def snapshot_coverage_context(
    repo: Path,
    run_dir: Path,
    scope_identity: dict[str, Any],
    context_paths: set[str],
    *,
    max_files: int = 32,
    max_file_bytes: int = 2 * 1024 * 1024,
    max_total_bytes: int = 25 * 1024 * 1024,
) -> dict[str, Any]:
    context, source_bytes = _build_coverage_context(
        repo,
        run_dir,
        scope_identity,
        context_paths,
        max_files=max_files,
        max_file_bytes=max_file_bytes,
        max_total_bytes=max_total_bytes,
    )
    destination = run_dir / "coverage-context"
    if artifact_exists(destination):
        raise ReviewError(
            "Coverage context artifact exists without a valid state binding; start a new run"
        )
    temporary = run_dir / f".coverage-context.initializing-{uuid.uuid4().hex[:8]}"
    artifact_mkdir(temporary, parents=False, exist_ok=False)
    try:
        for path, data in source_bytes.items():
            atomic_write_bytes(temporary / "sources" / path, data)
        artifact_rename(temporary, destination)
    except BaseException:
        artifact_remove(temporary, recursive=True, missing_ok=True)
        raise
    context_hash = canonical_hash(context)
    return {**context, "coverage_context_hash": context_hash}


def snapshot_sources(
    repo: Path,
    run_dir: Path,
    scope: dict[str, Any],
    *,
    max_file_bytes: int,
    max_total_bytes: int,
) -> list[str]:
    total = 0
    limitations: list[str] = []
    identity = scope["identity"]
    for entry in identity["files"]:
        for side in ("baseline", "comparison"):
            source_path = entry.get("old_path") if side == "baseline" and entry.get("old_path") else entry["path"]
            state_key = f"{side}_state"
            state_info = entry[state_key]
            if state_info.get("type") == "missing":
                continue
            if side == "baseline":
                data = git_object_bytes(repo, identity["baseline_sha"], source_path)
            elif identity["comparison_kind"] == "commit":
                data = git_object_bytes(repo, identity["comparison_sha"], source_path)
            else:
                target = repo_path(repo, source_path)
                if target.is_file() and not target.is_symlink():
                    data = target.read_bytes()
                elif target.is_symlink():
                    data = os.fsencode(os.readlink(target))
                else:
                    data = None
            if data is None:
                continue
            if len(data) > max_file_bytes:
                limitations.append(f"{side}:{source_path} not snapshotted ({len(data)} bytes exceeds per-file limit)")
                continue
            if total + len(data) > max_total_bytes:
                limitations.append(f"{side}:{source_path} not snapshotted (total snapshot limit reached)")
                continue
            destination = run_dir / "sources" / side / source_path
            atomic_write_bytes(destination, data)
            state_info["snapshot_path"] = str(destination.relative_to(run_dir)).replace("\\", "/")
            total += len(data)
    return limitations


def make_run_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"{stamp}-{uuid.uuid4().hex[:8]}"


def state_path(run_dir: Path) -> Path:
    return run_dir / "state.json"


def load_state(run_dir: Path) -> dict[str, Any]:
    state = require_object(load_json(state_path(run_dir)), "state")
    classify_state_contract(state, run_dir=run_dir)
    return state


def save_state(run_dir: Path, state: dict[str, Any]) -> None:
    state["updated_at"] = utc_now()
    atomic_write_json(state_path(run_dir), state)


def load_verified_scope(run_dir: Path, state: dict[str, Any]) -> dict[str, Any]:
    scope = require_object(load_json(run_dir / "scope.json"), "frozen scope")
    identity = require_object(scope.get("identity"), "frozen scope.identity")
    embedded = require_string(scope.get("scope_hash"), "frozen scope.scope_hash")
    recomputed = scope_identity_hash(identity)
    if embedded != recomputed or embedded != state.get("scope_hash"):
        raise ReviewError(
            "Frozen scope metadata failed integrity validation against its identity and state"
        )
    patch_checks = (
        ("scope.patch", "patch_sha256"),
        ("staged.patch", "staged_patch_sha256"),
        ("unstaged.patch", "unstaged_patch_sha256"),
    )
    for filename, identity_key in patch_checks:
        if sha256_file(run_dir / filename) != identity.get(identity_key):
            raise ReviewError(f"{filename} does not match the frozen scope identity")
    files_copy = load_json(run_dir / "files.json")
    if files_copy != identity.get("files"):
        raise ReviewError("files.json does not match scope.json identity.files")
    return scope


def load_verified_coverage_context(
    run_dir: Path,
    state: dict[str, Any],
    *,
    expected_paths: set[str],
) -> dict[str, Any]:
    artifact = require_object(
        load_json(run_dir / "coverage-context.json"), "coverage context"
    )
    context = copy.deepcopy(artifact)
    embedded_hash = require_sha256(
        context.pop("coverage_context_hash", None),
        "coverage context.coverage_context_hash",
    )
    recomputed_hash = canonical_hash(context)
    if recomputed_hash != embedded_hash:
        raise ReviewError(
            "Coverage context failed its embedded hash check: "
            f"expected {embedded_hash}, recomputed {recomputed_hash}"
        )
    require_state_hash(state, "coverage_context_hash", embedded_hash, "coverage context")
    require_exact_keys(
        context,
        {"schema_version", "scope_hash", "comparison_kind", "comparison_sha", "sources"},
        "coverage context",
    )
    if context["schema_version"] != COVERAGE_CONTEXT_SCHEMA:
        raise ReviewError("Coverage context has an unsupported schema_version")
    if context["scope_hash"] != state.get("scope_hash"):
        raise ReviewError("Coverage context scope_hash does not match the active run")
    scope_identity = load_verified_scope(run_dir, state)["identity"]
    if (
        context["comparison_kind"] != scope_identity["comparison_kind"]
        or context["comparison_sha"] != scope_identity["comparison_sha"]
    ):
        raise ReviewError("Coverage context comparison identity does not match the frozen scope")

    sources = require_array(context["sources"], "coverage context.sources")
    seen: set[str] = set()
    for index, raw_source in enumerate(sources):
        source_context = f"coverage context.sources[{index}]"
        source = require_object(raw_source, source_context)
        require_exact_keys(
            source,
            {"path", "sha256", "size", "snapshot_path"},
            source_context,
        )
        try:
            path = canonical_git_path(source["path"], f"{source_context}.path")
            snapshot_path = canonical_git_path(
                source["snapshot_path"], f"{source_context}.snapshot_path"
            )
        except ObligationContractError as exc:
            raise ReviewError(str(exc)) from exc
        expected_snapshot_path = f"coverage-context/sources/{path}"
        if snapshot_path != expected_snapshot_path:
            raise ReviewError(
                f"{source_context}.snapshot_path must equal {expected_snapshot_path}"
            )
        if path in seen:
            raise ReviewError("Coverage context source paths must be unique")
        seen.add(path)
        expected_sha = require_sha256(source["sha256"], f"{source_context}.sha256")
        expected_size = require_int(source["size"], f"{source_context}.size", minimum=0)
        snapshot = run_dir / snapshot_path
        try:
            data = artifact_read_bytes(snapshot)
        except OSError as exc:
            raise ReviewError(f"Could not read frozen coverage context {snapshot}: {exc}") from exc
        if len(data) != expected_size or sha256_bytes(data) != expected_sha:
            raise ReviewError(f"Frozen coverage context failed integrity validation: {path}")
    if seen != expected_paths:
        raise ReviewError(
            "Coverage context sources do not equal the coverage plan context paths"
        )
    return artifact


def load_recorded_coverage_plan(run_dir: Path, state: dict[str, Any]) -> dict[str, Any]:
    artifact = require_object(load_json(run_dir / "coverage-plan.json"), "coverage plan")
    plan = copy.deepcopy(artifact)
    embedded_hash = require_sha256(
        plan.pop("coverage_plan_hash", None), "coverage plan.coverage_plan_hash"
    )
    context_hash = require_sha256(
        plan.pop("coverage_context_hash", None), "coverage plan.coverage_context_hash"
    )
    context_paths = collect_coverage_context_paths(plan)
    context = load_verified_coverage_context(
        run_dir,
        state,
        expected_paths=context_paths,
    )
    if context["coverage_context_hash"] != context_hash:
        raise ReviewError("Coverage plan context hash does not match coverage-context.json")
    recomputed_hash = canonical_hash(
        {"plan": plan, "coverage_context_hash": context_hash}
    )
    if recomputed_hash != embedded_hash:
        raise ReviewError(
            f"Coverage plan failed its embedded hash check: expected {embedded_hash}, recomputed {recomputed_hash}"
        )
    require_state_hash(state, "coverage_plan_hash", embedded_hash, "coverage plan")
    validated = validate_coverage_plan(
        plan,
        run_dir=run_dir,
        state=state,
        allowed_context_paths=context_paths,
    )
    if validated != plan:
        raise ReviewError("Coverage plan is not stored in canonical normalized form")
    return validated


def validate_normalized_candidates_profile(
    bundle: dict[str, Any], *, state: dict[str, Any], plan: dict[str, Any] | None = None
) -> None:
    expected_schema = expected_normalized_candidates_schema(state)
    schema_version = require_string(
        bundle.get("schema_version"), "normalized candidates.schema_version"
    )
    if schema_version != expected_schema:
        raise ReviewError(
            "normalized candidates schema_version does not match the active workflow profile: "
            f"expected {expected_schema}, got {schema_version}"
        )
    if bundle.get("scope_hash") != state.get("scope_hash"):
        raise ReviewError("Normalized candidates scope_hash does not match the active run")

    reviewer_sets = require_array(
        bundle.get("reviewer_sets"), "normalized candidates.reviewer_sets"
    )
    candidates = require_array(bundle.get("candidates"), "normalized candidates.candidates")
    material_review = schema_version == NORMALIZED_CANDIDATES_SCHEMA_REVIEW

    if not material_review:
        for field in ("coverage_plan_hash", "coverage_context_hash"):
            if field in bundle:
                raise ReviewError(
                    f"Simplification normalized candidates must not contain {field}"
                )
        for index, raw_reviewer_set in enumerate(reviewer_sets):
            reviewer_set = require_object(
                raw_reviewer_set, f"normalized candidates.reviewer_sets[{index}]"
            )
            for field in (
                "lens_id",
                "assignment_id",
                "assignment_kind",
                "obligation_id",
                "check_results",
            ):
                if field in reviewer_set:
                    raise ReviewError(
                        f"Simplification normalized reviewer sets must not contain {field}"
                    )
        for index, raw_candidate in enumerate(candidates):
            candidate = require_object(
                raw_candidate, f"normalized candidates.candidates[{index}]"
            )
            for field in ("lens_id", "assignment_id"):
                if field in candidate:
                    raise ReviewError(
                        f"Simplification normalized candidates must not contain {field}"
                    )
        return

    if plan is None:
        raise ReviewError("Normalized material-review candidates require a coverage plan")

    coverage_plan_hash = require_sha256(
        bundle.get("coverage_plan_hash"),
        "normalized candidates.coverage_plan_hash",
    )
    if coverage_plan_hash != state.get("hashes", {}).get("coverage_plan_hash"):
        raise ReviewError(
            "Normalized candidates coverage_plan_hash does not match the recorded coverage plan"
        )
    coverage_context_hash = require_sha256(
        bundle.get("coverage_context_hash"),
        "normalized candidates.coverage_context_hash",
    )
    if coverage_context_hash != state.get("hashes", {}).get("coverage_context_hash"):
        raise ReviewError(
            "Normalized candidates coverage_context_hash does not match the recorded coverage context"
        )

    assignments = {item["assignment_id"]: item for item in plan["assignments"]}
    reviewer_sets_by_assignment: dict[str, dict[str, Any]] = {}
    for index, raw_reviewer_set in enumerate(reviewer_sets):
        context = f"normalized candidates.reviewer_sets[{index}]"
        reviewer_set = require_object(raw_reviewer_set, context)
        assignment_id = require_string(
            reviewer_set.get("assignment_id"), f"{context}.assignment_id"
        )
        if assignment_id in reviewer_sets_by_assignment:
            raise ReviewError(
                f"Duplicate normalized reviewer-set assignment_id: {assignment_id}"
            )
        assignment = assignments.get(assignment_id)
        if assignment is None:
            raise ReviewError(f"{context}.assignment_id is absent from the coverage plan")
        for field in (
            "assignment_kind",
            "lens_id",
            "reviewer_id",
            "independence_group",
            "review_mode",
        ):
            if reviewer_set.get(field) != assignment.get(field):
                raise ReviewError(f"{context}.{field} does not match the coverage assignment")
        expected_obligation_id = assignment.get("obligation_id")
        if reviewer_set.get("obligation_id") != expected_obligation_id:
            if expected_obligation_id is not None or "obligation_id" in reviewer_set:
                raise ReviewError(
                    f"{context}.obligation_id does not match the coverage assignment"
                )
        specialist_fields = ("unit_ids", "primary_paths", "context_paths")
        if assignment["assignment_kind"] == "specialist":
            for field in specialist_fields:
                if reviewer_set.get(field) != assignment[field]:
                    raise ReviewError(
                        f"{context}.{field} does not match the coverage assignment"
                    )
        else:
            unexpected_specialist_fields = [
                field for field in specialist_fields if field in reviewer_set
            ]
            if unexpected_specialist_fields:
                raise ReviewError(
                    f"{context} has specialist provenance for a non-specialist assignment"
                )
        for field in ("required_review_paths", "required_checks"):
            if reviewer_set.get(field) != assignment[field]:
                raise ReviewError(
                    f"{context}.{field} does not match the coverage assignment"
                )
        expected_scenarios = scenario_checks_for_assignment(plan, assignment)
        if reviewer_set.get("scenario_checks") != expected_scenarios:
            raise ReviewError(
                f"{context}.scenario_checks do not match the coverage plan"
            )
        expected_check_contracts = check_contracts_for_assignment(plan, assignment)
        if reviewer_set.get("check_contracts") != expected_check_contracts:
            raise ReviewError(
                f"{context}.check_contracts do not match the machine-owned obligation contracts"
            )
        reviewer_coverage_hash = require_sha256(
            reviewer_set.get("coverage_plan_hash"), f"{context}.coverage_plan_hash"
        )
        if reviewer_coverage_hash != coverage_plan_hash:
            raise ReviewError(
                f"{context}.coverage_plan_hash does not match the normalized bundle"
            )
        reviewer_context_hash = require_sha256(
            reviewer_set.get("coverage_context_hash"),
            f"{context}.coverage_context_hash",
        )
        if reviewer_context_hash != coverage_context_hash:
            raise ReviewError(
                f"{context}.coverage_context_hash does not match the normalized bundle"
            )
        reviewer_sets_by_assignment[assignment_id] = reviewer_set

    missing_assignments = sorted(
        required_assignment_ids(plan) - set(reviewer_sets_by_assignment)
    )
    if missing_assignments:
        raise ReviewError(
            "Normalized candidates are missing assignments: "
            + ", ".join(missing_assignments)
        )

    candidate_ids: set[str] = set()
    for index, raw_candidate in enumerate(candidates):
        context = f"normalized candidates.candidates[{index}]"
        candidate = require_object(raw_candidate, context)
        candidate_id = require_string(candidate.get("candidate_id"), f"{context}.candidate_id")
        if candidate_id in candidate_ids:
            raise ReviewError(f"Duplicate normalized candidate_id: {candidate_id}")
        candidate_ids.add(candidate_id)
        assignment_id = require_string(
            candidate.get("assignment_id"), f"{context}.assignment_id"
        )
        reviewer_set = reviewer_sets_by_assignment.get(assignment_id)
        if reviewer_set is None:
            raise ReviewError(
                f"{context}.assignment_id has no validated reviewer-set source"
            )
        candidate_identity = (
            candidate.get("lens_id"),
            candidate.get("reviewer_id"),
            candidate.get("independence_group"),
            candidate.get("review_mode"),
        )
        reviewer_set_identity = (
            reviewer_set.get("lens_id"),
            reviewer_set.get("reviewer_id"),
            reviewer_set.get("independence_group"),
            reviewer_set.get("review_mode"),
        )
        if candidate_identity != reviewer_set_identity:
            raise ReviewError(
                f"{context} identity does not match its validated assignment source"
            )
        if "coverage_plan_hash" in candidate or "coverage_context_hash" in candidate:
            raise ReviewError(
                f"{context} must not duplicate the bundle coverage hashes"
            )

    for assignment_id, reviewer_set in reviewer_sets_by_assignment.items():
        check_results = require_array(
            reviewer_set.get("check_results"),
            f"normalized reviewer set {assignment_id}.check_results",
        )
        for check_index, raw_check in enumerate(check_results):
            check = require_object(
                raw_check,
                f"normalized reviewer set {assignment_id}.check_results[{check_index}]",
            )
            if "finding_local_ids" in check:
                raise ReviewError(
                    "Normalized obligation checks must resolve finding_local_ids to candidate_ids"
                )
            referenced = set(
                require_string_array(
                    check.get("candidate_ids"),
                    f"normalized reviewer set {assignment_id}.check_results[{check_index}].candidate_ids",
                )
            )
            unknown = sorted(referenced - candidate_ids)
            if unknown:
                raise ReviewError(
                    "Normalized obligation check references unknown candidate IDs: "
                    + ", ".join(unknown)
                )


def load_verified_candidates_bundle(
    run_dir: Path, state: dict[str, Any]
) -> dict[str, Any]:
    bundle = require_object(
        load_json(run_dir / "candidates.json"), "normalized candidates"
    )
    plan = None
    if classify_state_contract(state) == STATE_CONTRACT_MATERIAL_REVIEW:
        plan = load_recorded_coverage_plan(run_dir, state)
    validate_normalized_candidates_profile(bundle, state=state, plan=plan)
    bundle_hash = verify_embedded_hash(
        bundle,
        hash_field="candidate_bundle_hash",
        context="normalized candidates",
        unhashed_fields={"generated_at"},
    )
    require_state_hash(
        state, "candidate_bundle_hash", bundle_hash, "normalized candidates"
    )
    return bundle


def require_compatible_existing_candidate_authority(
    run_dir: Path, state: dict[str, Any]
) -> dict[str, Any]:
    try:
        return load_verified_candidates_bundle(run_dir, state)
    except ReviewError as exc:
        raise ReviewError(
            "Existing normalized candidate authority is incompatible with the active "
            "workflow profile; start a new run. Cause: " + str(exc)
        ) from exc


def load_verified_findings_gate(run_dir: Path, state: dict[str, Any]) -> dict[str, Any]:
    receipt = require_object(load_json(run_dir / "gates" / "findings.json"), "Gate A receipt")
    receipt_hash = verify_embedded_hash(
        receipt,
        hash_field="receipt_hash",
        context="Gate A receipt",
    )
    require_state_gate(state, "findings", receipt_hash, "Gate A receipt")
    require_state_hash(state, "findings_gate_hash", receipt_hash, "Gate A receipt")
    return receipt


def load_verified_ledger(
    run_dir: Path,
    state: dict[str, Any],
    *,
    findings_gate: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ledger = require_object(load_json(run_dir / "ledger.json"), "ledger")
    expected_schema = expected_ledger_schema(state)
    schema_version = require_string(ledger.get("schema_version"), "ledger.schema_version")
    if schema_version != expected_schema:
        raise ReviewError(
            "ledger schema_version does not match the active workflow profile: "
            f"expected {expected_schema}, got {schema_version}"
        )
    entries = [
        *require_array(ledger.get("findings"), "ledger.findings"),
        *require_array(ledger.get("discarded"), "ledger.discarded"),
    ]
    if schema_version == LEDGER_SCHEMA_REVIEW:
        candidates_bundle = load_verified_candidates_bundle(run_dir, state)
        candidates_by_id = {
            candidate["candidate_id"]: candidate
            for candidate in candidates_bundle["candidates"]
        }
        for index, raw_entry in enumerate(entries):
            context = f"ledger provenance entry[{index}]"
            entry = require_object(raw_entry, context)
            candidate_ids = require_string_array(
                entry.get("candidate_ids"), f"{context}.candidate_ids"
            )
            unknown = sorted(set(candidate_ids) - set(candidates_by_id))
            if unknown:
                raise ReviewError(
                    f"{context} references unknown candidate IDs: {', '.join(unknown)}"
                )
            expected_lenses = sorted(
                {candidates_by_id[candidate_id]["lens_id"] for candidate_id in candidate_ids}
            )
            source_lenses = require_string_array(
                entry.get("source_lenses"), f"{context}.source_lenses"
            )
            if source_lenses != expected_lenses:
                raise ReviewError(
                    f"{context}.source_lenses must be the exact sorted candidate-source lenses"
                )
    else:
        for index, raw_entry in enumerate(entries):
            entry = require_object(raw_entry, f"ledger provenance entry[{index}]")
            if "source_lenses" in entry:
                raise ReviewError(
                    "Simplification ledger/v3 entries must not contain source_lenses"
                )
    ledger_hash = verify_embedded_hash(
        ledger,
        hash_field="ledger_hash",
        context="ledger",
        unhashed_fields={"generated_at"},
    )
    require_state_hash(state, "ledger_hash", ledger_hash, "ledger")
    if findings_gate is not None and findings_gate.get("ledger_hash") != ledger_hash:
        raise ReviewError("Ledger does not match the hash recorded by Gate A")
    return ledger


def load_verified_plan(run_dir: Path, state: dict[str, Any]) -> dict[str, Any]:
    plan = require_object(load_json(run_dir / "fix-plan.json"), "fix plan")
    plan_hash = verify_embedded_hash(
        plan,
        hash_field="plan_hash",
        context="fix plan",
        unhashed_fields={"validated_at"},
    )
    require_state_hash(state, "plan_hash", plan_hash, "fix plan")
    return plan


def load_verified_plan_gate(run_dir: Path, state: dict[str, Any]) -> dict[str, Any]:
    receipt = require_object(load_json(run_dir / "gates" / "plan.json"), "Gate B receipt")
    receipt_hash = verify_embedded_hash(
        receipt,
        hash_field="receipt_hash",
        context="Gate B receipt",
    )
    require_state_gate(state, "plan", receipt_hash, "Gate B receipt")
    require_state_hash(state, "plan_gate_hash", receipt_hash, "Gate B receipt")
    return receipt


def load_verified_fix_summary(run_dir: Path, state: dict[str, Any]) -> dict[str, Any]:
    summary = require_object(load_json(run_dir / "fix-summary.json"), "fix summary")
    summary_hash = verify_embedded_hash(
        summary,
        hash_field="fix_summary_hash",
        context="fix summary",
    )
    require_state_hash(state, "fix_summary_hash", summary_hash, "fix summary")
    patch_path = run_dir / "fix-summary.patch"
    if sha256_file(patch_path) != summary.get("fix_patch_sha256"):
        raise ReviewError("fix-summary.patch does not match fix-summary.json")
    return summary


def resolve_run_dir(args: argparse.Namespace, repo: Path) -> tuple[Path, Path]:
    artifact_root = resolve_artifact_root(repo, getattr(args, "artifact_root", None))
    runs_root = artifact_root / "runs"
    raw_run_id = getattr(args, "run_id", None) or os.environ.get("MATERIAL_REVIEW_RUN_ID")
    run_id = normalize_run_id(raw_run_id) if raw_run_id else None
    active_authority = _ACTIVE_ARTIFACT_AUTHORITY
    if active_authority is not None:
        run_dir = runs_root / run_id if run_id else active_authority.root_path
        if active_authority._relative_parts(run_dir) != ():
            raise ReviewError(
                "The active artifact authority does not match the requested run"
            )
        state = load_state(run_dir)
        if Path(state.get("repo_root", "")).resolve() != repo:
            raise ReviewError(
                f"Run {state.get('run_id')} belongs to {state.get('repo_root')}, "
                f"not the requested repository {repo}"
            )
        return artifact_root, run_dir
    if run_id:
        run_dir = runs_root / run_id
        try:
            authority = RunArtifactAuthority(run_dir)
        except ReviewError as error:
            raise ReviewError(f"Run not found: {run_id} under {runs_root}") from error
        _install_active_artifact_authority(authority)
        if not artifact_exists(state_path(run_dir)):
            raise ReviewError(f"Run not found: {run_id} under {runs_root}")
        state = load_state(run_dir)
        if Path(state.get("repo_root", "")).resolve() != repo:
            raise ReviewError(
                f"Run {run_id} belongs to {state.get('repo_root')}, not the requested repository {repo}"
            )
        return artifact_root, run_dir

    try:
        runs_authority = RunArtifactAuthority(runs_root)
    except ReviewError as error:
        raise ReviewError(
            "No material-code-review runs exist; run init first or pass --run-id"
        ) from error
    candidates: list[Path] = []
    all_repo_runs: list[Path] = []
    with active_artifact_authority(runs_authority):
        for name in artifact_list_names(runs_root):
            path = runs_root / name
            if not artifact_exists(state_path(path)):
                continue
            try:
                state = load_state(path)
            except ReviewError:
                continue
            if Path(state.get("repo_root", "")).resolve() != repo:
                continue
            all_repo_runs.append(path)
            if state.get("phase") not in {PHASE_COMPLETE, PHASE_ABORTED}:
                candidates.append(path)
    selected: Path | None = None
    if len(candidates) == 1:
        selected = candidates[0]
    elif not candidates and len(all_repo_runs) == 1:
        selected = all_repo_runs[0]
    elif not candidates:
        raise ReviewError(
            "No unique active run found; pass --run-id or set MATERIAL_REVIEW_RUN_ID"
        )
    else:
        raise ReviewError(
            "Multiple active runs found: "
            + ", ".join(path.name for path in candidates)
            + ". Pass --run-id."
        )
    _install_active_artifact_authority(RunArtifactAuthority(selected))
    return artifact_root, selected


def write_source_bundle_files(run_dir: Path, scope: dict[str, Any], limitations: list[str]) -> None:
    atomic_write_bytes(run_dir / "scope.patch", scope["patch"])
    atomic_write_bytes(run_dir / "staged.patch", scope["staged_patch"])
    atomic_write_bytes(run_dir / "unstaged.patch", scope["unstaged_patch"])
    identity = copy.deepcopy(scope["identity"])
    atomic_write_json(
        run_dir / "scope.json",
        {
            "schema_version": SCOPE_SCHEMA,
            "scope_hash": scope["scope_hash"],
            "identity": identity,
            "snapshot_limitations": limitations,
            "captured_at": utc_now(),
        },
    )
    atomic_write_json(run_dir / "files.json", identity["files"])
    lines = [
        "# Frozen review scope",
        "",
        f"- Scope hash: `{scope['scope_hash']}`",
        f"- Mode: `{identity['actual_scope']}`",
        f"- Baseline: `{identity['base_reference']}` -> `{identity['baseline_sha']}`",
        f"- Comparison: `{identity['comparison_reference']}` -> `{identity['comparison_sha']}`",
        f"- Mutable/aligned: `{str(identity['mutable']).lower()}`",
        f"- Include untracked: `{str(identity['include_untracked']).lower()}`",
        "",
        "## Files",
        "",
    ]
    for entry in identity["files"]:
        rename = f" (from `{entry['old_path']}`)" if entry.get("old_path") else ""
        lines.append(f"- `{entry['status']}` `{entry['path']}`{rename}")
    if limitations:
        lines.extend(["", "## Snapshot limitations", ""])
        lines.extend(f"- {item}" for item in limitations)
    atomic_write_text(run_dir / "scope.md", "\n".join(lines) + "\n")


def recompute_scope_from_state(repo: Path, state: dict[str, Any]) -> dict[str, Any]:
    params = state["scope_params"]
    return build_scope(
        repo,
        requested_scope=params["actual_scope"],
        base_ref=params.get("base_reference"),
        head_ref=params.get("head_reference"),
        include_untracked=bool(params["include_untracked"]),
    )


def check_scope_fresh(repo: Path, run_dir: Path, state: dict[str, Any]) -> dict[str, Any]:
    if state["phase"] in MUTATION_PHASES:
        raise ReviewError("Original scope freshness is not used after begin-fix; use checkpoint/workspace controls")
    current = recompute_scope_from_state(repo, state)
    if current["scope_hash"] != state["scope_hash"]:
        report = {
            "expected_scope_hash": state["scope_hash"],
            "current_scope_hash": current["scope_hash"],
            "checked_at": utc_now(),
            "expected_identity": load_json(run_dir / "scope.json")["identity"],
            "current_identity": current["identity"],
        }
        atomic_write_json(run_dir / "scope-staleness.json", report)
        raise ReviewError(
            "Frozen review scope is stale. See scope-staleness.json; reinitialize or regenerate downstream artifacts."
        )
    return current


def workspace_status_paths(repo: Path) -> set[str]:
    data = git_bytes(repo, "status", "--porcelain=v1", "-z", "--untracked-files=all")
    paths = parse_status_paths_z(data)
    tracked_raw = git_bytes(repo, "ls-files", "-z")
    tracked = {normalize_repo_path(os.fsdecode(raw)) for raw in tracked_raw.split(b"\0") if raw}
    return {path for path in paths if path in tracked or not is_transient_runtime_path(path)}


def workspace_guard(repo: Path) -> dict[str, Any]:
    paths = sorted(workspace_status_paths(repo))
    states = {path: path_state(repo_path(repo, path)) for path in paths}
    staged = git_bytes(repo, "diff", "--cached", "--binary", "--full-index", "HEAD", "--")
    unstaged = git_bytes(repo, "diff", "--binary", "--full-index", "--")
    identity = {
        "head_sha": resolve_commit(repo, "HEAD"),
        "branch": current_branch(repo),
        "staged_patch_sha256": sha256_bytes(staged),
        "unstaged_patch_sha256": sha256_bytes(unstaged),
        "path_states": states,
    }
    return {"identity": identity, "guard_hash": canonical_hash(identity)}


def index_identity(repo: Path) -> dict[str, Any]:
    raw_path = git_text(repo, "rev-parse", "--git-path", "index")
    path = Path(raw_path)
    if not path.is_absolute():
        path = repo / path
    path = path.resolve(strict=False)
    if not path.exists():
        return {"path": str(path), "present": False, "sha256": None, "size": None}
    if not path.is_file():
        raise ReviewError("Git index path is not a regular file")
    staged_entries = git_bytes(repo, "ls-files", "--stage", "-z")
    entry_flags = git_bytes(repo, "ls-files", "-v", "-z")
    content = staged_entries + b"\0--entry-flags--\0" + entry_flags
    return {
        "path": str(path),
        "present": True,
        "sha256": sha256_bytes(content),
        "size": len(content),
    }


def repository_authority(repo: Path) -> dict[str, Any]:
    guard = workspace_guard(repo)
    identity = {
        "head_attachment": current_head_attachment(repo),
        "head_sha": resolve_commit(repo, "HEAD"),
        "refs": repository_refs(repo),
        "index": index_identity(repo),
        "workspace_guard": guard,
    }
    return {"identity": identity, "authority_hash": canonical_hash(identity)}


def diff_guard_paths(before: dict[str, Any], after: dict[str, Any]) -> set[str]:
    before_states = before["identity"]["path_states"]
    after_states = after["identity"]["path_states"]
    paths = set(before_states) | set(after_states)
    return {path for path in paths if before_states.get(path, {"type": "clean"}) != after_states.get(path, {"type": "clean"})}


def repository_control_mutations(
    before: dict[str, Any], after: dict[str, Any]
) -> list[str]:
    before_identity = before["identity"]
    after_identity = after["identity"]
    labels: list[str] = []
    if before_identity["head_sha"] != after_identity["head_sha"]:
        labels.append("HEAD")
    if before_identity["head_attachment"] != after_identity["head_attachment"]:
        labels.append("HEAD attachment")
    if before_identity["refs"] != after_identity["refs"]:
        labels.append("refs namespace")
    if before_identity["index"] != after_identity["index"]:
        labels.append("Git index")
    return labels


def ensure_expected_workspace(repo: Path, state: dict[str, Any]) -> dict[str, Any]:
    current = workspace_guard(repo)
    expected = state.get("expected_workspace_guard_hash")
    if expected and current["guard_hash"] != expected:
        raise ReviewError(
            "Workspace drifted outside the controlled repair sequence. Reconcile user/tool changes before proceeding."
        )
    return current


def snapshot_copy_path(repo: Path, snapshot_root: Path, path: str, state_info: dict[str, Any]) -> None:
    source = repo_path(repo, path)
    destination = snapshot_root / "content" / path
    if state_info["type"] == "file":
        atomic_write_bytes(destination, source.read_bytes())
    elif state_info["type"] == "symlink":
        atomic_write_text(destination.with_suffix(destination.suffix + ".symlink"), state_info["target"])


def create_checkpoint(repo: Path, checkpoint_dir: Path, extra_paths: Iterable[str]) -> dict[str, Any]:
    if artifact_exists(checkpoint_dir):
        raise ReviewError(f"Checkpoint already exists: {checkpoint_dir}")
    artifact_mkdir(checkpoint_dir, parents=True, exist_ok=False)
    try:
        authority = repository_authority(repo)
        authority_identity = authority["identity"]
        guard = authority_identity["workspace_guard"]
        paths = set(guard["identity"]["path_states"])
        paths.update(normalize_repo_path(path) for path in extra_paths)
        path_states: dict[str, Any] = {}
        for path in sorted(paths):
            info = path_state(repo_path(repo, path))
            path_states[path] = info
            snapshot_copy_path(repo, checkpoint_dir, path, info)

        index = authority_identity["index"]
        index_path = Path(index["path"])
        index_backup = checkpoint_dir / "index.backup"
        if index["present"]:
            atomic_write_bytes(index_backup, index_path.read_bytes())
            index_backup_sha256 = sha256_file(index_backup)
        else:
            index_backup_sha256 = None

        if repository_authority(repo) != authority:
            raise ReviewError("Repository authority changed while the checkpoint was captured")

        refs = authority_identity["refs"]
        metadata = {
            "schema_version": CHECKPOINT_SCHEMA_V4,
            "created_at": utc_now(),
            "head_sha": authority_identity["head_sha"],
            "branch": guard["identity"]["branch"],
            "head_attachment": authority_identity["head_attachment"],
            "refs": refs,
            "local_head_refs": {
                ref: object_id
                for ref, object_id in refs.items()
                if ref.startswith("refs/heads/")
            },
            "repository_authority": authority,
            "workspace_guard": guard,
            "path_states": path_states,
            "index_path": index["path"],
            "index_present": index["present"],
            "index_sha256": index_backup_sha256,
        }
        metadata["checkpoint_hash"] = canonical_hash(
            {key: value for key, value in metadata.items() if key != "created_at"}
        )
        atomic_write_json(checkpoint_dir / "checkpoint.json", metadata)
        return metadata
    except BaseException:
        artifact_remove(checkpoint_dir, recursive=True, missing_ok=True)
        raise


def remove_path(path: Path) -> None:
    artifact_remove(path, recursive=True, missing_ok=True)


def restore_one_snapshot_path(repo: Path, checkpoint_dir: Path, path: str, info: dict[str, Any]) -> None:
    target = repo_path(repo, path)
    kind = info["type"]
    if kind == "missing":
        remove_path(target)
        return
    if kind == "directory":
        if artifact_exists(target) and not artifact_is_dir(target):
            remove_path(target)
        artifact_mkdir(target, parents=True, exist_ok=True)
        os.chmod(target, info.get("mode", 0o755))
        return
    if kind == "file":
        if artifact_exists(target) or artifact_is_symlink(target):
            remove_path(target)
        artifact_mkdir(target.parent, parents=True, exist_ok=True)
        source = checkpoint_dir / "content" / path
        target.write_bytes(artifact_read_bytes(source))
        os.chmod(target, info.get("mode", 0o644))
        return
    if kind == "symlink":
        if artifact_exists(target) or artifact_is_symlink(target):
            remove_path(target)
        artifact_mkdir(target.parent, parents=True, exist_ok=True)
        link_target_path = (checkpoint_dir / "content" / path).with_suffix(
            (checkpoint_dir / "content" / path).suffix + ".symlink"
        )
        link_target = artifact_read_text(link_target_path, encoding="utf-8")
        os.symlink(link_target, target)
        return
    raise ReviewError(f"Cannot restore unsupported file type for {path}: {kind}")


def path_exists_in_head(repo: Path, path: str) -> bool:
    result = run_process(["git", "cat-file", "-e", f"HEAD:{path}"], cwd=repo, check=False)
    return result.returncode == 0


def validate_ref_map(value: Any, context: str) -> dict[str, str]:
    raw_refs = require_object(value, context)
    refs: dict[str, str] = {}
    for raw_ref, raw_object_id in raw_refs.items():
        ref = require_string(raw_ref, f"{context} ref")
        object_id = require_string(raw_object_id, f"{context}.{ref}")
        if (
            not ref.startswith("refs/")
            or ref == "refs/"
            or re.fullmatch(r"[0-9a-f]{40,64}", object_id) is None
            or ref in refs
        ):
            raise ReviewError(f"{context} contains invalid ref data")
        refs[ref] = object_id
    return dict(sorted(refs.items()))


def validate_repository_authority(value: Any, context: str) -> dict[str, Any]:
    authority = require_object(value, context)
    require_exact_keys(authority, {"identity", "authority_hash"}, context)
    identity = require_object(authority.get("identity"), f"{context}.identity")
    require_exact_keys(
        identity,
        {"head_attachment", "head_sha", "refs", "index", "workspace_guard"},
        f"{context}.identity",
    )
    authority_hash = require_sha256(
        authority.get("authority_hash"), f"{context}.authority_hash"
    )
    if authority_hash != canonical_hash(identity):
        raise ReviewError(f"{context} failed its embedded hash check")
    attachment = identity.get("head_attachment")
    if attachment is not None:
        attachment = require_string(attachment, f"{context}.identity.head_attachment")
        if not attachment.startswith("refs/heads/") or attachment == "refs/heads/":
            raise ReviewError(f"{context} has an invalid HEAD attachment")
    head_sha = require_string(identity.get("head_sha"), f"{context}.identity.head_sha")
    if re.fullmatch(r"[0-9a-f]{40,64}", head_sha) is None:
        raise ReviewError(f"{context}.identity.head_sha is not an object ID")
    refs = validate_ref_map(identity.get("refs"), f"{context}.identity.refs")
    if attachment is not None and refs.get(attachment) != head_sha:
        raise ReviewError(f"{context} attached HEAD does not match its saved ref")
    index = require_object(identity.get("index"), f"{context}.identity.index")
    require_exact_keys(index, {"path", "present", "sha256", "size"}, f"{context}.identity.index")
    require_string(index.get("path"), f"{context}.identity.index.path")
    present = require_bool(index.get("present"), f"{context}.identity.index.present")
    if present:
        require_sha256(index.get("sha256"), f"{context}.identity.index.sha256")
        require_int(index.get("size"), f"{context}.identity.index.size", minimum=0)
    elif index.get("sha256") is not None or index.get("size") is not None:
        raise ReviewError(f"{context}.identity.index has content metadata while absent")
    guard = require_object(
        identity.get("workspace_guard"), f"{context}.identity.workspace_guard"
    )
    guard_identity = require_object(
        guard.get("identity"), f"{context}.identity.workspace_guard.identity"
    )
    if guard.get("guard_hash") != canonical_hash(guard_identity):
        raise ReviewError(f"{context} workspace guard failed its embedded hash check")
    if (
        guard_identity.get("head_sha") != head_sha
        or guard_identity.get("branch")
        != (attachment.removeprefix("refs/heads/") if attachment else "DETACHED")
    ):
        raise ReviewError(f"{context} workspace guard has contradictory HEAD identity")
    return authority


def verify_checkpoint_integrity(
    repo: Path,
    checkpoint_dir: Path,
    *,
    require_current_ref: bool = False,
) -> tuple[dict[str, Any], dict[str, Any], Path]:
    """Validate checkpoint metadata, snapshots, and Git-index backup before use.

    Checkpoints are used both for restoration and as the authoritative repair
    baseline.  Verifying them only during restore would let a corrupted baseline
    influence path authorization or rendered diffs before corruption is noticed.
    """
    metadata = require_object(load_json(checkpoint_dir / "checkpoint.json"), "checkpoint")
    verify_embedded_hash(
        metadata,
        hash_field="checkpoint_hash",
        context="checkpoint",
        unhashed_fields={"created_at"},
    )
    guard = require_object(metadata.get("workspace_guard"), "checkpoint.workspace_guard")
    guard_identity = require_object(guard.get("identity"), "checkpoint.workspace_guard.identity")
    if guard.get("guard_hash") != canonical_hash(guard_identity):
        raise ReviewError("Checkpoint workspace guard failed its embedded hash check")
    checkpoint_head = require_string(metadata.get("head_sha"), "checkpoint.head_sha")
    checkpoint_branch = require_string(metadata.get("branch"), "checkpoint.branch")
    if guard_identity.get("head_sha") != checkpoint_head or guard_identity.get("branch") != checkpoint_branch:
        raise ReviewError("Checkpoint top-level Git identity does not match its workspace guard")
    if metadata.get("schema_version") is not None:
        if metadata.get("schema_version") != CHECKPOINT_SCHEMA_V4:
            raise ReviewError("Checkpoint has an unsupported schema_version")
        authority = validate_repository_authority(
            metadata.get("repository_authority"), "checkpoint.repository_authority"
        )
        authority_identity = authority["identity"]
        refs = validate_ref_map(metadata.get("refs"), "checkpoint.refs")
        if (
            authority_identity["head_sha"] != checkpoint_head
            or authority_identity["head_attachment"] != metadata.get("head_attachment")
            or authority_identity["refs"] != refs
            or authority_identity["workspace_guard"] != guard
        ):
            raise ReviewError("Checkpoint repository authority contradicts top-level metadata")
    if require_current_ref and (
        resolve_commit(repo, "HEAD") != checkpoint_head or current_branch(repo) != checkpoint_branch
    ):
        raise ReviewError("Cannot restore automatically because HEAD or branch changed after the checkpoint")

    current_index_raw = git_text(repo, "rev-parse", "--git-path", "index")
    current_index_path = Path(current_index_raw)
    if not current_index_path.is_absolute():
        current_index_path = repo / current_index_path
    current_index_path = current_index_path.resolve(strict=False)
    recorded_index_path = Path(require_string(metadata.get("index_path"), "checkpoint.index_path")).resolve(strict=False)
    if current_index_path != recorded_index_path:
        raise ReviewError("Checkpoint index path does not match the repository's current Git index")
    if metadata.get("schema_version") == CHECKPOINT_SCHEMA_V4:
        recorded_index = metadata["repository_authority"]["identity"]["index"]
        if (
            recorded_index["path"] != str(recorded_index_path)
            or recorded_index["present"] != metadata.get("index_present")
        ):
            raise ReviewError("Checkpoint index authority contradicts top-level metadata")

    raw_path_states = require_object(metadata.get("path_states"), "checkpoint.path_states")
    path_states: dict[str, Any] = {}
    for raw_path, raw_info in raw_path_states.items():
        path = normalize_repo_path(require_string(raw_path, "checkpoint path"))
        if path in path_states:
            raise ReviewError(f"Checkpoint contains duplicate normalized path: {path}")
        info = require_object(raw_info, f"checkpoint.path_states.{path}")
        path_states[path] = info
        kind = require_string(info.get("type"), f"checkpoint.path_states.{path}.type")
        if kind == "file":
            source = checkpoint_dir / "content" / path
            if not artifact_is_file(source) or artifact_is_symlink(source):
                raise ReviewError(f"Checkpoint file snapshot is missing or invalid: {path}")
            if info.get("sha256") and sha256_file(source) != info["sha256"]:
                raise ReviewError(f"Checkpoint file snapshot failed its hash check: {path}")
            if info.get("size") is not None and len(artifact_read_bytes(source)) != info["size"]:
                raise ReviewError(f"Checkpoint file snapshot failed its size check: {path}")
        elif kind == "symlink":
            source = (checkpoint_dir / "content" / path).with_suffix(
                (checkpoint_dir / "content" / path).suffix + ".symlink"
            )
            if not artifact_is_file(source):
                raise ReviewError(f"Checkpoint symlink snapshot is missing: {path}")
            if artifact_read_text(source, encoding="utf-8") != info.get("target"):
                raise ReviewError(f"Checkpoint symlink snapshot failed its target check: {path}")
        elif kind not in {"missing", "directory"}:
            raise ReviewError(f"Checkpoint contains unsupported file type for {path}: {kind}")

    if require_bool(metadata.get("index_present"), "checkpoint.index_present"):
        backup = checkpoint_dir / "index.backup"
        if not artifact_is_file(backup):
            raise ReviewError("Checkpoint Git index backup is missing")
        if sha256_file(backup) != metadata.get("index_sha256"):
            raise ReviewError("Checkpoint Git index backup failed its hash check")
    elif metadata.get("index_sha256") is not None:
        raise ReviewError("Checkpoint records an index hash although no index was present")

    return metadata, path_states, current_index_path


def restore_legacy_checkpoint(repo: Path, checkpoint_dir: Path) -> dict[str, Any]:
    metadata, path_states, current_index_path = verify_checkpoint_integrity(
        repo,
        checkpoint_dir,
        require_current_ref=True,
    )

    current_paths = workspace_status_paths(repo)
    snap_paths = set(path_states)
    for path in sorted(current_paths - snap_paths):
        target = repo_path(repo, path)
        if path_exists_in_head(repo, path):
            run_process(["git", "restore", "--source=HEAD", "--worktree", "--", path], cwd=repo, check=True)
        else:
            remove_path(target)

    index_path = current_index_path
    if metadata["index_present"]:
        artifact_mkdir(index_path.parent, parents=True, exist_ok=True)
        temp_index = index_path.with_name(f".{index_path.name}.material-review.tmp")
        temp_index.write_bytes(artifact_read_bytes(checkpoint_dir / "index.backup"))
        artifact_rename(temp_index, index_path)
    else:
        artifact_remove(index_path, missing_ok=True)

    for path, info in path_states.items():
        restore_one_snapshot_path(repo, checkpoint_dir, normalize_repo_path(path), info)

    current = workspace_guard(repo)
    expected_hash = metadata["workspace_guard"]["guard_hash"]
    if current["guard_hash"] != expected_hash:
        atomic_write_json(
            checkpoint_dir / "restore-mismatch.json",
            {
                "expected": metadata["workspace_guard"],
                "current": current,
                "checked_at": utc_now(),
            },
        )
        raise ReviewError("Checkpoint restoration did not reproduce the original workspace; human recovery is required")
    return current


def verify_v4_checkpoint(
    repo: Path, checkpoint_dir: Path
) -> tuple[dict[str, Any], dict[str, Any], Path]:
    metadata, path_states, index_path = verify_checkpoint_integrity(
        repo, checkpoint_dir, require_current_ref=False
    )
    if metadata.get("schema_version") != CHECKPOINT_SCHEMA_V4:
        raise ReviewError("Checkpoint predates v4 repository-authority recovery")
    return metadata, path_states, index_path


def write_recovery_evidence(
    checkpoint_dir: Path,
    filename: str,
    *,
    checkpoint_authority: dict[str, Any],
    expected_post: dict[str, Any],
    observed_current: dict[str, Any],
    reason: str,
) -> None:
    atomic_write_json(
        checkpoint_dir / filename,
        {
            "schema_version": "material-review/recovery-evidence/v1",
            "reason": reason,
            "checkpoint_authority": checkpoint_authority,
            "expected_post": expected_post,
            "observed_current": observed_current,
            "checked_at": utc_now(),
        },
    )


def observe_repository_after_recovery_failure(
    repo: Path, primary_error: BaseException
) -> dict[str, Any]:
    """Best-effort authority evidence that cannot mask a recovery failure."""
    try:
        return repository_authority(repo)
    except BaseException as observation_error:
        observed: dict[str, Any] = {
            "observation_incomplete": True,
            "observation_error": (
                f"{type(observation_error).__name__}: {observation_error}"
            ),
            "primary_error": f"{type(primary_error).__name__}: {primary_error}",
        }
        probes = (
            ("head_attachment", current_head_attachment),
            ("refs", repository_refs),
            ("index", index_identity),
        )
        for field, probe in probes:
            try:
                observed[field] = probe(repo)
            except BaseException as probe_error:
                observed[f"{field}_error"] = (
                    f"{type(probe_error).__name__}: {probe_error}"
                )
        try:
            paths = sorted(workspace_status_paths(repo))
            observed["workspace_paths"] = paths
            observed["workspace_path_states"] = {
                path: path_state(repo_path(repo, path)) for path in paths
            }
        except BaseException as probe_error:
            observed["workspace_error"] = (
                f"{type(probe_error).__name__}: {probe_error}"
            )
        return observed


def manual_recovery_observation(
    repo: Path,
    checkpoint_dir: Path,
    *,
    allowed_paths: Iterable[str],
    context: str,
) -> dict[str, Any]:
    """Bind manual recovery only to repository state the plan authorized."""
    metadata = require_object(
        load_json(checkpoint_dir / "checkpoint.json"), "checkpoint"
    )
    if metadata.get("schema_version") != CHECKPOINT_SCHEMA_V4:
        return repository_authority(repo)

    metadata, _, _ = verify_v4_checkpoint(repo, checkpoint_dir)
    checkpoint_authority = validate_repository_authority(
        metadata.get("repository_authority"), "checkpoint.repository_authority"
    )
    current = repository_authority(repo)
    checkpoint_guard = checkpoint_authority["identity"]["workspace_guard"]
    current_guard = current["identity"]["workspace_guard"]
    normalized_allowed = {
        normalize_repo_path(path) for path in allowed_paths
    }
    changed_paths = diff_guard_paths(checkpoint_guard, current_guard)
    outside_paths = changed_paths - normalized_allowed
    control_mutations = repository_control_mutations(checkpoint_authority, current)
    if not outside_paths and not control_mutations:
        return current

    details: list[str] = []
    if control_mutations:
        details.append("repository controls: " + ", ".join(control_mutations))
    if outside_paths:
        details.append("paths: " + ", ".join(sorted(outside_paths)))
    expected_boundary = {
        "schema_version": "material-review/manual-recovery-boundary/v1",
        "allowed_paths": sorted(normalized_allowed),
        "checkpoint_repository_controls": {
            key: checkpoint_authority["identity"][key]
            for key in ("head_attachment", "head_sha", "refs", "index")
        },
    }
    reason = (
        f"{context} includes changes not authorized for automatic recovery ("
        + "; ".join(details)
        + ")"
    )
    write_recovery_evidence(
        checkpoint_dir,
        "recovery-conflict.json",
        checkpoint_authority=checkpoint_authority,
        expected_post=expected_boundary,
        observed_current=current,
        reason=reason,
    )
    raise ReviewError(reason + "; repository state was preserved for human reconciliation")


def plan_v4_worktree_recovery(
    repo: Path,
    path_states: dict[str, Any],
) -> list[tuple[str, dict[str, Any]]]:
    """Plan only worktree writes that can prove an expected-missing boundary."""

    snapshot_paths = set(path_states)
    unexpected_paths = sorted(workspace_status_paths(repo) - snapshot_paths)
    conflicts = [f"{path}: not present in the checkpoint" for path in unexpected_paths]
    actions: list[tuple[str, dict[str, Any]]] = []
    for path, desired in sorted(path_states.items()):
        target = repo_path(repo, path)
        current = path_state(target)
        if current == desired:
            continue
        if current["type"] != "missing":
            conflicts.append(
                f"{path}: {current['type']} to {desired['type']} requires existing-path replacement or deletion"
            )
            continue
        if desired["type"] == "missing":
            continue
        if desired["type"] not in {"file", "directory", "symlink"}:
            conflicts.append(
                f"{path}: unsupported checkpoint type {desired['type']}"
            )
            continue
        if path_state(target.parent)["type"] != "directory":
            conflicts.append(f"{path}: parent directory is not present and unchanged")
            continue
        actions.append((path, desired))
    if conflicts:
        raise ReviewError(
            "Automatic worktree recovery cannot conditionally apply: "
            + "; ".join(conflicts)
        )
    return actions


def probe_v4_symbolic_ref_transactions(
    repo: Path,
    observed_identity: dict[str, Any],
) -> None:
    """Verify symbolic-ref transaction support without committing a ref change."""

    observed_attachment = observed_identity["head_attachment"]
    if observed_attachment is None:
        command = (
            "symref-update HEAD refs/heads/material-review-capability-probe "
            f"oid {observed_identity['head_sha']}"
        )
    else:
        command = (
            f"symref-update HEAD {observed_attachment} ref {observed_attachment}"
        )
    transaction = f"start\noption no-deref\n{command}\nprepare\nabort\n".encode(
        "utf-8"
    )
    try:
        run_process(
            ["git", "update-ref", "--stdin"],
            cwd=repo,
            input_bytes=transaction,
        )
    except BaseException as exc:
        raise ReviewError(
            "Git lacks the required conditional symbolic-ref transaction support"
        ) from exc


def v4_ref_transaction(
    saved_identity: dict[str, Any],
    observed_identity: dict[str, Any],
) -> bytes:
    """Build ordered expected-old transactions for HEAD and the complete ref delta."""

    saved_attachment = saved_identity["head_attachment"]
    observed_attachment = observed_identity["head_attachment"]
    saved_refs = saved_identity["refs"]
    observed_refs = observed_identity["refs"]

    def ref_command(ref: str) -> str | None:
        saved = saved_refs.get(ref)
        observed = observed_refs.get(ref)
        if saved == observed:
            return None
        if saved is None:
            return f"delete {ref} {observed}"
        if observed is None:
            return f"create {ref} {saved}"
        return f"update {ref} {saved} {observed}"

    deferred_ref = (
        observed_attachment
        if observed_attachment is not None and observed_attachment != saved_attachment
        else None
    )
    prepared_ref_commands = [
        command
        for ref in sorted(set(saved_refs) | set(observed_refs))
        if ref != deferred_ref
        if (command := ref_command(ref)) is not None
    ]

    transaction: list[str] = []

    def append_transaction(commands: list[str]) -> None:
        if commands:
            transaction.extend(["start", *commands, "prepare", "commit"])

    append_transaction(prepared_ref_commands)
    if saved_attachment is None:
        head_commands = [
            "option no-deref",
            (
                f"update HEAD {saved_identity['head_sha']} "
                f"{observed_identity['head_sha']}"
            ),
        ]
    else:
        expected = (
            f"ref {observed_attachment}"
            if observed_attachment is not None
            else f"oid {observed_identity['head_sha']}"
        )
        head_commands = [
            "option no-deref",
            f"symref-update HEAD {saved_attachment} {expected}",
        ]
    append_transaction(head_commands)

    if deferred_ref is not None:
        deferred_command = ref_command(deferred_ref)
        if deferred_command is not None:
            append_transaction([deferred_command])

    return ("\n".join(transaction) + "\n").encode("utf-8")


def acquire_v4_index_lock(
    repo: Path,
    index_path: Path,
    expected_index: dict[str, Any],
) -> tuple[int, Path]:
    """Acquire Git's cooperative index lock and recheck semantic identity."""

    lock_path = index_path.with_name(f"{index_path.name}.lock")
    try:
        descriptor = os.open(lock_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise ReviewError(f"Git index lock is already held: {lock_path}") from exc
    try:
        if index_identity(repo) != expected_index:
            raise ReviewError("Git index changed before its conditional recovery boundary")
    except BaseException:
        os.close(descriptor)
        lock_path.unlink(missing_ok=True)
        raise
    return descriptor, lock_path


def restore_v4_index(
    checkpoint_dir: Path,
    index_path: Path,
    saved_index: dict[str, Any],
    observed_index: dict[str, Any],
    descriptor: int,
    lock_path: Path,
) -> None:
    """Restore the index while holding the canonical cooperative Git lock."""

    if saved_index == observed_index:
        os.close(descriptor)
        lock_path.unlink(missing_ok=True)
        return
    if saved_index["present"]:
        with os.fdopen(descriptor, "wb") as locked_index:
            locked_index.write(
                artifact_read_bytes(checkpoint_dir / "index.backup")
            )
            locked_index.flush()
            os.fsync(locked_index.fileno())
        os.replace(lock_path, index_path)
        return

    os.close(descriptor)
    if index_path.exists():
        index_path.unlink()
    lock_path.unlink(missing_ok=True)


def execute_v4_worktree_recovery(
    repo: Path,
    checkpoint_dir: Path,
    actions: list[tuple[str, dict[str, Any]]],
) -> None:
    """Create checkpoint paths only when the destination is still absent."""

    for path, desired in actions:
        target = repo_path(repo, path)
        kind = desired["type"]
        if kind == "directory":
            target.mkdir(mode=desired.get("mode", 0o755), exist_ok=False)
            os.chmod(target, desired.get("mode", 0o755))
        elif kind == "symlink":
            os.symlink(desired["target"], target)
        elif kind == "file":
            temporary = target.with_name(
                f".{target.name}.material-review-v4-{uuid.uuid4().hex}.tmp"
            )
            descriptor = os.open(
                temporary,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                desired.get("mode", 0o644),
            )
            try:
                with os.fdopen(descriptor, "wb") as destination:
                    destination.write(
                        artifact_read_bytes(checkpoint_dir / "content" / path)
                    )
                    destination.flush()
                    os.fsync(destination.fileno())
                os.chmod(temporary, desired.get("mode", 0o644))
                os.link(temporary, target)
            finally:
                temporary.unlink(missing_ok=True)
        else:
            raise ReviewError(f"Unsupported conditional worktree action for {path}: {kind}")


def restore_checkpoint_v4(
    repo: Path,
    checkpoint_dir: Path,
    *,
    expected_post: dict[str, Any],
) -> dict[str, Any]:
    metadata, path_states, index_path = verify_v4_checkpoint(repo, checkpoint_dir)
    checkpoint_authority = validate_repository_authority(
        metadata["repository_authority"], "checkpoint.repository_authority"
    )
    expected_post = validate_repository_authority(
        expected_post, "recovery expected_post"
    )
    observed_current = repository_authority(repo)
    if observed_current != expected_post:
        write_recovery_evidence(
            checkpoint_dir,
            "recovery-conflict.json",
            checkpoint_authority=checkpoint_authority,
            expected_post=expected_post,
            observed_current=observed_current,
            reason="Repository authority changed after the recovery observation",
        )
        raise ReviewError(
            "Repository authority changed after the recovery observation; no recovery write was attempted"
        )

    saved_identity = checkpoint_authority["identity"]
    observed_identity = expected_post["identity"]
    try:
        worktree_actions = plan_v4_worktree_recovery(repo, path_states)
        probe_v4_symbolic_ref_transactions(repo, observed_identity)
        index_descriptor, index_lock_path = acquire_v4_index_lock(
            repo,
            index_path,
            observed_identity["index"],
        )
    except BaseException as exc:
        observed_after_conflict = observe_repository_after_recovery_failure(repo, exc)
        write_recovery_evidence(
            checkpoint_dir,
            "recovery-conflict.json",
            checkpoint_authority=checkpoint_authority,
            expected_post=expected_post,
            observed_current=observed_after_conflict,
            reason=f"Conditional recovery preflight failed: {exc}",
        )
        raise ReviewError(
            f"Conditional recovery preflight failed; repository authority was preserved for human reconciliation: {exc}"
        ) from exc

    index_lock_owned = True
    try:
        run_process(
            ["git", "update-ref", "--stdin"],
            cwd=repo,
            input_bytes=v4_ref_transaction(saved_identity, observed_identity),
        )
        restore_v4_index(
            checkpoint_dir,
            index_path,
            saved_identity["index"],
            observed_identity["index"],
            index_descriptor,
            index_lock_path,
        )
        index_lock_owned = False
        execute_v4_worktree_recovery(repo, checkpoint_dir, worktree_actions)
    except BaseException as exc:
        if index_lock_owned:
            try:
                os.close(index_descriptor)
            except OSError:
                pass
            index_lock_path.unlink(missing_ok=True)
        current_after_failure = observe_repository_after_recovery_failure(repo, exc)
        write_recovery_evidence(
            checkpoint_dir,
            "recovery-failure.json",
            checkpoint_authority=checkpoint_authority,
            expected_post=expected_post,
            observed_current=current_after_failure,
            reason=f"Recovery write failed: {exc}",
        )
        raise ReviewError(
            f"Checkpoint recovery was incomplete; human recovery is required: {exc}"
        ) from exc

    restored = repository_authority(repo)
    if restored != checkpoint_authority:
        write_recovery_evidence(
            checkpoint_dir,
            "recovery-mismatch.json",
            checkpoint_authority=checkpoint_authority,
            expected_post=expected_post,
            observed_current=restored,
            reason="Recovery did not reproduce the checkpoint authority",
        )
        raise ReviewError(
            "Checkpoint recovery did not reproduce the saved repository authority; human recovery is required"
        )
    return restored


def restore_checkpoint(
    repo: Path,
    checkpoint_dir: Path,
    *,
    expected_post: dict[str, Any] | None = None,
) -> dict[str, Any]:
    metadata = require_object(
        load_json(checkpoint_dir / "checkpoint.json"), "checkpoint"
    )
    if metadata.get("schema_version") == CHECKPOINT_SCHEMA_V4:
        if expected_post is None:
            raise ReviewError(
                "v4 checkpoint recovery requires a caller-bound expected post-command observation"
            )
        return restore_checkpoint_v4(
            repo, checkpoint_dir, expected_post=expected_post
        )
    if metadata.get("schema_version") is not None:
        raise ReviewError("Checkpoint has an unsupported schema_version")
    return restore_legacy_checkpoint(repo, checkpoint_dir)


def restore_refresh_checkpoint(
    repo: Path,
    checkpoint_dir: Path,
    *,
    expected_post: dict[str, Any],
) -> dict[str, Any]:
    """Compatibility alias for the single v4 recovery engine."""
    return restore_checkpoint(repo, checkpoint_dir, expected_post=expected_post)


def verify_frozen_source_bytes(
    data: bytes | None, state_info: dict[str, Any], *, label: str
) -> bytes | None:
    if data is None:
        if state_info.get("type") != "missing":
            raise ReviewError(f"Frozen source {label} is missing but scope metadata expected content")
        return None
    expected = state_info.get("sha256")
    if expected and sha256_bytes(data) != expected:
        raise ReviewError(f"Frozen source {label} failed its content hash check")
    if state_info.get("size") is not None and len(data) != state_info["size"]:
        raise ReviewError(f"Frozen source {label} failed its size check")
    return data


def snapshot_entry_for_side(
    scope_identity: dict[str, Any], side: str, path: str
) -> dict[str, Any] | None:
    entries = scope_identity["files"]
    if side == "comparison":
        matches = [entry for entry in entries if entry["path"] == path]
    elif side == "baseline":
        renamed_or_copied = [
            entry for entry in entries if entry.get("old_path") == path
        ]
        matches = renamed_or_copied or [
            entry
            for entry in entries
            if entry.get("old_path") is None and entry["path"] == path
        ]
    else:
        raise ReviewError(f"Unsupported frozen source side: {side}")
    if not matches:
        return None
    first_state = matches[0][f"{side}_state"]
    if any(entry[f"{side}_state"] != first_state for entry in matches[1:]):
        raise ReviewError(f"Frozen scope has contradictory {side} identity for path: {path}")
    return matches[0]


def read_snapshot_source(
    run_dir: Path,
    scope_identity: dict[str, Any],
    side: str,
    path: str,
    repo: Path,
) -> tuple[str, bytes | None]:
    entry = snapshot_entry_for_side(scope_identity, side, path)
    if entry is None:
        return SNAPSHOT_NO_MATCH, None
    state_info = entry[f"{side}_state"]
    if state_info.get("type") == "missing":
        verify_frozen_source_bytes(None, state_info, label=f"{side}:{path}")
        return SNAPSHOT_MATCHED_MISSING, None
    snapshot_path = state_info.get("snapshot_path")
    if snapshot_path:
        data = artifact_read_bytes(run_dir / snapshot_path)
    elif side == "baseline":
        source_path = entry.get("old_path") or entry["path"]
        data = git_object_bytes(repo, scope_identity["baseline_sha"], source_path)
    elif scope_identity["comparison_kind"] == "commit":
        data = git_object_bytes(repo, scope_identity["comparison_sha"], entry["path"])
    else:
        target = repo_path(repo, entry["path"])
        if target.is_file() and not target.is_symlink():
            data = target.read_bytes()
        elif target.is_symlink():
            data = os.fsencode(os.readlink(target))
        else:
            data = None
    verified = verify_frozen_source_bytes(data, state_info, label=f"{side}:{path}")
    assert verified is not None
    return SNAPSHOT_MATCHED_BYTES, verified


def read_coverage_context_source(
    run_dir: Path, coverage_context: dict[str, Any], path: str
) -> bytes | None:
    for source in coverage_context["sources"]:
        if source["path"] != path:
            continue
        data = artifact_read_bytes(run_dir / source["snapshot_path"])
        if len(data) != source["size"] or sha256_bytes(data) != source["sha256"]:
            raise ReviewError(f"Frozen coverage context failed integrity validation: {path}")
        return data
    return None

def verify_evidence_quote(
    *,
    repo: Path,
    run_dir: Path,
    scope_identity: dict[str, Any],
    file: str,
    line_start: int,
    line_end: int,
    side: str,
    quote: str,
    coverage_context: dict[str, Any] | None = None,
) -> None:
    if side == "diff":
        patch = artifact_read_text(
            run_dir / "scope.patch", encoding="utf-8", errors="replace"
        )
        stripped = "\n".join(line[1:] if line[:1] in {"+", "-", " "} else line for line in patch.splitlines())
        if quote not in patch and quote not in stripped:
            raise ReviewError(f"Evidence quote for {file}:{line_start} was not found in the frozen diff")
        return

    snapshot_outcome, data = read_snapshot_source(
        run_dir, scope_identity, side, file, repo
    )
    if (
        snapshot_outcome == SNAPSHOT_NO_MATCH
        and side == "comparison"
        and coverage_context is not None
    ):
        data = read_coverage_context_source(run_dir, coverage_context, file)
    if data is None:
        raise ReviewError(f"Evidence source is missing for {side}:{file}")
    text = data.decode("utf-8", errors="replace")
    lines = text.splitlines()
    if line_start > len(lines):
        raise ReviewError(f"Evidence line {line_start} exceeds {side}:{file} length {len(lines)}")
    line_end = min(line_end, len(lines))
    region = "\n".join(lines[line_start - 1 : line_end])
    if quote not in region:
        if quote in text:
            raise ReviewError(f"Evidence quote exists in {side}:{file} but not at lines {line_start}-{line_end}")
        raise ReviewError(f"Evidence quote was not found in {side}:{file}")


def render_path_diff(checkpoint_dir: Path, repo: Path, path: str, before: dict[str, Any], after: dict[str, Any]) -> str:
    header = f"# {path}\n"
    if before == after:
        return ""
    if before.get("type") == "file":
        before_bytes = artifact_read_bytes(checkpoint_dir / "content" / path)
    elif before.get("type") == "symlink":
        before_bytes = before.get("target", "").encode("utf-8")
    else:
        before_bytes = b""
    target = repo_path(repo, path)
    if after.get("type") == "file":
        after_bytes = target.read_bytes()
    elif after.get("type") == "symlink":
        after_bytes = os.fsencode(os.readlink(target))
    else:
        after_bytes = b""
    if bytes_are_binary(before_bytes) or bytes_are_binary(after_bytes):
        return (
            header
            + f"Binary/state change: {before.get('type')} {before.get('sha256', '-')} -> "
            + f"{after.get('type')} {after.get('sha256', '-')}\n"
        )
    before_text = before_bytes.decode("utf-8", errors="replace").splitlines(keepends=True)
    after_text = after_bytes.decode("utf-8", errors="replace").splitlines(keepends=True)
    return "".join(
        difflib.unified_diff(before_text, after_text, fromfile=f"a/{path}", tofile=f"b/{path}", lineterm="\n")
    )


def render_checkpoint_diff(checkpoint_dir: Path, repo: Path, changed_paths: Iterable[str]) -> str:
    _, path_states, _ = verify_checkpoint_integrity(repo, checkpoint_dir)
    chunks: list[str] = []
    for path in sorted(changed_paths):
        before = path_states.get(path, {"type": "missing"})
        after = path_state(repo_path(repo, path))
        chunk = render_path_diff(checkpoint_dir, repo, path, before, after)
        if chunk:
            chunks.append(chunk)
    return "\n".join(chunks)


def validate_coverage_plan(
    raw: object,
    *,
    run_dir: Path,
    state: dict[str, Any],
    allowed_context_paths: set[str] | None = None,
) -> dict[str, Any]:
    scope = load_verified_scope(run_dir, state)
    changed_paths = {entry["path"] for entry in scope["identity"]["files"]}
    if allowed_context_paths is None:
        allowed_context_paths = collect_coverage_context_paths(
            require_object(raw, "coverage plan")
        )
    try:
        plan = validate_coverage_contract(
            raw,
            changed_paths=changed_paths,
            allowed_context_paths=allowed_context_paths,
        )
    except ObligationContractError as exc:
        raise ReviewError(str(exc)) from exc
    if plan["scope_hash"] != state.get("scope_hash"):
        raise ReviewError("coverage plan scope hash does not match the active frozen scope")
    return plan


def validate_candidate_set(
    raw: Any,
    *,
    source_file: Path,
    repo: Path,
    run_dir: Path,
    state: dict[str, Any],
    plan: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    obj = require_object(raw, f"candidate set {source_file}")
    material_review = not is_simplification_state(state)
    expected_schema = CANDIDATE_SCHEMA_REVIEW if material_review else CANDIDATE_SCHEMA
    schema_version = require_string(obj.get("schema_version"), f"{source_file}.schema_version")
    if schema_version != expected_schema:
        raise ReviewError(f"{source_file}: unsupported schema_version")
    assignment: dict[str, Any] | None = None
    obligation: dict[str, Any] | None = None
    assignment_id: str | None = None
    assignment_kind: str | None = None
    coverage_plan_hash: str | None = None
    coverage_context_hash: str | None = None
    lens_id: str | None = None
    check_results: list[dict[str, Any]] = []
    if material_review:
        if plan is None:
            raise ReviewError("Material-review candidate validation requires a coverage plan")
        assignment_id = require_string(
            obj.get("assignment_id"), f"{source_file}.assignment_id"
        )
        assignment = next(
            (
                item
                for item in plan["assignments"]
                if item["assignment_id"] == assignment_id
            ),
            None,
        )
        if assignment is None:
            raise ReviewError(f"{source_file}: assignment_id is absent from the coverage plan")
        if assignment["assignment_kind"] == "obligation":
            obligation = next(
                (
                    item
                    for item in plan["review_obligations"]
                    if item["obligation_id"] == assignment["obligation_id"]
                ),
                None,
            )
        try:
            obj = validate_assignment_result(
                obj,
                assignment=assignment,
                obligation=obligation,
            )
        except ObligationContractError as exc:
            raise ReviewError(f"{source_file}: {exc}") from exc
        assignment_kind = obj["assignment_kind"]
        coverage_plan_hash = obj["coverage_plan_hash"]
        coverage_context_hash = obj["coverage_context_hash"]
        lens_id = obj["lens_id"]
        check_results = obj["check_results"]
    else:
        expected_top = {
            "schema_version",
            "scope_hash",
            "reviewer_id",
            "independence_group",
            "review_mode",
            "findings",
            "coverage",
        }
        require_exact_keys(obj, expected_top, f"candidate set {source_file}")
    prevalidated_coverage_files: list[str] | None = None
    prevalidated_finding_paths: dict[int, dict[str, Any]] = {}
    if material_review:
        coverage_for_path_preflight = require_object(
            obj["coverage"], f"{source_file}.coverage"
        )
        if "files_reviewed" in coverage_for_path_preflight:
            prevalidated_coverage_files = require_canonical_repo_path_array(
                coverage_for_path_preflight["files_reviewed"],
                f"{source_file}.coverage.files_reviewed",
            )
        findings_for_path_preflight = require_array(
            obj["findings"], f"{source_file}.findings"
        )
        for index, raw_finding in enumerate(findings_for_path_preflight):
            context = f"{source_file}.findings[{index}]"
            finding = require_object(raw_finding, context)
            path_fields: dict[str, Any] = {}
            if "file" in finding:
                path_fields["file"] = require_canonical_repo_path(
                    finding["file"], f"{context}.file"
                )
            if "related_changed_files" in finding:
                path_fields["related_changed_files"] = require_canonical_repo_path_array(
                    finding["related_changed_files"],
                    f"{context}.related_changed_files",
                )
            prevalidated_finding_paths[index] = path_fields
    if obj["scope_hash"] != state["scope_hash"]:
        raise ReviewError(f"{source_file}: scope_hash does not match the active frozen scope")
    if material_review:
        if coverage_plan_hash != state["hashes"].get("coverage_plan_hash"):
            raise ReviewError(f"{source_file}: coverage_plan_hash does not match the recorded coverage plan")
        if coverage_context_hash != state["hashes"].get("coverage_context_hash"):
            raise ReviewError(
                f"{source_file}: coverage_context_hash does not match the recorded coverage context"
            )
    reviewer_id = require_string(obj["reviewer_id"], f"{source_file}.reviewer_id")
    independence_group = require_string(obj["independence_group"], f"{source_file}.independence_group")
    review_mode = require_string(obj["review_mode"], f"{source_file}.review_mode")
    if review_mode not in REVIEW_MODES:
        raise ReviewError(f"{source_file}.review_mode must be one of {sorted(REVIEW_MODES)}")

    coverage = require_object(obj["coverage"], f"{source_file}.coverage")
    require_exact_keys(coverage, {"files_reviewed", "areas", "limitations"}, f"{source_file}.coverage")
    if material_review:
        assert prevalidated_coverage_files is not None
        coverage_files = prevalidated_coverage_files
    else:
        coverage_files = [
            normalize_repo_path(item)
            for item in require_string_array(
                coverage["files_reviewed"], f"{source_file}.coverage.files_reviewed"
            )
        ]
    if material_review and not coverage_files:
        raise ReviewError(
            f"{source_file}.coverage.files_reviewed must name at least one frozen-scope path"
        )
    coverage_areas = require_string_array(coverage["areas"], f"{source_file}.coverage.areas")
    coverage_limitations = (
        copy.deepcopy(coverage["limitations"])
        if material_review
        else require_string_array(
            coverage["limitations"], f"{source_file}.coverage.limitations"
        )
    )

    scope_info = load_verified_scope(run_dir, state)
    scope_identity = scope_info["identity"]
    scope_paths = all_scope_paths(scope_identity)
    coverage_context: dict[str, Any] | None = None
    if material_review:
        assert plan is not None
        coverage_context = load_verified_coverage_context(
            run_dir,
            state,
            expected_paths=collect_coverage_context_paths(plan),
        )
        if coverage_context["coverage_context_hash"] != coverage_context_hash:
            raise ReviewError(
                f"{source_file}: coverage_context_hash does not match verified frozen context"
            )
    findings_raw = require_array(obj["findings"], f"{source_file}.findings")
    valid_findings: list[dict[str, Any]] = []
    rejections: list[dict[str, Any]] = []
    local_ids: set[str] = set()
    finding_keys = {
        "local_id",
        "title",
        "nature",
        "category",
        "severity",
        "confidence",
        "file",
        "line_start",
        "line_end",
        "evidence_side",
        "evidence_quote",
        "scope_relation",
        "related_changed_files",
        "direct_dependency",
        "observable_consequence",
        "trigger_conditions",
        "counterevidence_checked",
        "why_not_preference",
        "proposed_resolution",
        "estimated_fix_risk",
        "requires_user_decision",
        "assumptions",
    }

    for index, raw_finding in enumerate(findings_raw):
        context = f"{source_file}.findings[{index}]"
        try:
            finding = require_object(raw_finding, context)
            require_exact_keys(finding, finding_keys, context)
            local_id = require_string(finding["local_id"], f"{context}.local_id")
            if local_id in local_ids:
                raise ReviewError(f"{context}.local_id is duplicated: {local_id}")
            local_ids.add(local_id)
            title = require_string(finding["title"], f"{context}.title")
            if len(title) > 140:
                raise ReviewError(f"{context}.title exceeds 140 characters")
            nature = require_string(finding["nature"], f"{context}.nature")
            category = require_string(finding["category"], f"{context}.category")
            severity = require_string(finding["severity"], f"{context}.severity")
            confidence = require_string(finding["confidence"], f"{context}.confidence")
            if nature not in NATURES:
                raise ReviewError(f"{context}.nature must be one of {sorted(NATURES)}")
            if category not in CATEGORIES:
                raise ReviewError(f"{context}.category must be one of {sorted(CATEGORIES)}")
            if severity not in SEVERITIES:
                raise ReviewError(f"{context}.severity must be one of {sorted(SEVERITIES)}")
            if confidence not in CONFIDENCES:
                raise ReviewError(f"{context}.confidence must be one of {sorted(CONFIDENCES)}")
            if confidence == "low" and severity != "blocker":
                raise ReviewError(f"{context}: low-confidence non-blocker candidates must be suppressed")

            if material_review:
                file = prevalidated_finding_paths[index]["file"]
            else:
                file = normalize_repo_path(require_string(finding["file"], f"{context}.file"))
            line_start = require_int(finding["line_start"], f"{context}.line_start", minimum=1)
            line_end = require_int(finding["line_end"], f"{context}.line_end", minimum=1)
            if line_end < line_start:
                raise ReviewError(f"{context}.line_end must be >= line_start")
            evidence_side = require_string(finding["evidence_side"], f"{context}.evidence_side")
            if evidence_side not in EVIDENCE_SIDES:
                raise ReviewError(f"{context}.evidence_side must be one of {sorted(EVIDENCE_SIDES)}")
            evidence_quote = require_string(finding["evidence_quote"], f"{context}.evidence_quote")
            scope_relation = require_string(finding["scope_relation"], f"{context}.scope_relation")
            if scope_relation not in SCOPE_RELATIONS:
                raise ReviewError(f"{context}.scope_relation must be one of {sorted(SCOPE_RELATIONS)}")
            if material_review:
                related = prevalidated_finding_paths[index]["related_changed_files"]
            else:
                related = [
                    normalize_repo_path(item)
                    for item in require_string_array(
                        finding["related_changed_files"], f"{context}.related_changed_files"
                    )
                ]
            direct_dependency = require_bool(finding["direct_dependency"], f"{context}.direct_dependency")
            if scope_relation == "primary" and file not in scope_paths:
                raise ReviewError(f"{context}: primary file is not part of the frozen changed-file set")
            if scope_relation == "secondary":
                if not related or not any(path in scope_paths for path in related):
                    raise ReviewError(f"{context}: secondary finding must name at least one frozen changed file")
            if scope_relation == "pre_existing" and file not in scope_paths and not direct_dependency:
                # It may be captured for visible rejection, but require an explicit changed-file relation.
                if not related or not any(path in scope_paths for path in related):
                    raise ReviewError(f"{context}: pre-existing candidate must name its changed-file relation")

            counterevidence = require_string_array(finding["counterevidence_checked"], f"{context}.counterevidence_checked")
            if confidence in {"certain", "high"} and not counterevidence:
                raise ReviewError(f"{context}: high/certain confidence requires checked counterevidence")
            estimated_fix_risk = require_string(finding["estimated_fix_risk"], f"{context}.estimated_fix_risk")
            if estimated_fix_risk not in FIX_RISKS:
                raise ReviewError(f"{context}.estimated_fix_risk must be one of {sorted(FIX_RISKS)}")

            verify_evidence_quote(
                repo=repo,
                run_dir=run_dir,
                scope_identity=scope_identity,
                file=file,
                line_start=line_start,
                line_end=line_end,
                side=evidence_side,
                quote=evidence_quote,
                coverage_context=coverage_context,
            )

            normalized = {
                "candidate_id": None,
                "reviewer_id": reviewer_id,
                "independence_group": independence_group,
                "review_mode": review_mode,
                "source_file": str(source_file),
                "local_id": local_id,
                "title": title,
                "nature": nature,
                "category": category,
                "severity": severity,
                "confidence": confidence,
                "file": file,
                "line_start": line_start,
                "line_end": line_end,
                "evidence_side": evidence_side,
                "evidence_quote": evidence_quote,
                "scope_relation": scope_relation,
                "related_changed_files": related,
                "direct_dependency": direct_dependency,
                "observable_consequence": require_string(finding["observable_consequence"], f"{context}.observable_consequence"),
                "trigger_conditions": require_string(finding["trigger_conditions"], f"{context}.trigger_conditions"),
                "counterevidence_checked": counterevidence,
                "why_not_preference": require_string(finding["why_not_preference"], f"{context}.why_not_preference"),
                "proposed_resolution": require_string(finding["proposed_resolution"], f"{context}.proposed_resolution"),
                "estimated_fix_risk": estimated_fix_risk,
                "requires_user_decision": require_bool(finding["requires_user_decision"], f"{context}.requires_user_decision"),
                "assumptions": require_string_array(finding["assumptions"], f"{context}.assumptions"),
            }
            valid_findings.append(normalized)
        except ReviewError as exc:
            rejections.append({"source_file": str(source_file), "index": index, "reason": str(exc)})

    if findings_raw and not valid_findings:
        reasons = "; ".join(item["reason"] for item in rejections[:3])
        suffix = f": {reasons}" if reasons else ""
        raise ReviewError(f"{source_file}: every submitted finding failed validation{suffix}")
    if material_review and rejections:
        raise ReviewError(
            f"{source_file}: candidate set includes invalid finding: {rejections[0]['reason']}"
        )

    normalized_set = {
        "reviewer_id": reviewer_id,
        "independence_group": independence_group,
        "review_mode": review_mode,
        "coverage": {
            "files_reviewed": coverage_files,
            "areas": coverage_areas,
            "limitations": coverage_limitations,
        },
        "findings": valid_findings,
    }
    if material_review:
        normalized_set.update(
            {
                "coverage_plan_hash": coverage_plan_hash,
                "coverage_context_hash": coverage_context_hash,
                "assignment_id": assignment_id,
                "assignment_kind": assignment_kind,
                "lens_id": lens_id,
                "check_results": check_results,
                "required_review_paths": assignment["required_review_paths"],
                "required_checks": assignment["required_checks"],
                "scenario_checks": scenario_checks_for_assignment(plan, assignment),
                "check_contracts": check_contracts_for_assignment(plan, assignment),
            }
        )
        if obligation is not None:
            normalized_set["obligation_id"] = obligation["obligation_id"]
        if assignment_kind == "specialist":
            assert assignment is not None
            for field in ("unit_ids", "primary_paths", "context_paths"):
                normalized_set[field] = assignment[field]
    return normalized_set, rejections


def required_paths_by_assignment(plan: dict[str, Any]) -> dict[str, set[str]]:
    return {
        assignment["assignment_id"]: set(assignment["required_review_paths"])
        for assignment in plan["assignments"]
    }


def validate_candidate_wave_against_coverage(
    plan: dict[str, Any], candidate_sets: list[dict[str, Any]]
) -> None:
    assignments = {item["assignment_id"]: item for item in plan["assignments"]}
    required_paths = required_paths_by_assignment(plan)
    seen: set[str] = set()
    for candidate_set in candidate_sets:
        assignment_id = candidate_set["assignment_id"]
        if assignment_id in seen:
            raise ReviewError(f"Duplicate candidate assignment_id: {assignment_id}")
        seen.add(assignment_id)
        assignment = assignments.get(assignment_id)
        if assignment is None:
            raise ReviewError(f"Assignment is absent from coverage plan: {assignment_id}")
        blocked_checks = [
            item["check_code"]
            for item in candidate_set["check_results"]
            if item["outcome"] == "blocked"
        ]
        if blocked_checks:
            raise ReviewError(
                f"Assignment {assignment_id} has blocked required checks: "
                + ", ".join(sorted(blocked_checks))
            )
        missing_paths = required_paths[assignment_id] - set(
            candidate_set["coverage"]["files_reviewed"]
        )
        if missing_paths:
            raise ReviewError(
                f"{assignment_id} did not review required assignment paths: "
                + ", ".join(sorted(missing_paths))
            )
    missing = sorted(required_assignment_ids(plan) - seen)
    if missing:
        raise ReviewError("Missing required assignment coverage: " + ", ".join(missing))


def validate_material_review_coverage_paths(
    candidate_sets: list[dict[str, Any]], *, allowed_paths: set[str]
) -> None:
    for candidate_set in candidate_sets:
        out_of_scope = set(candidate_set["coverage"]["files_reviewed"]) - allowed_paths
        if out_of_scope:
            raise ReviewError(
                "coverage.files_reviewed contains a path outside the frozen scope: "
                + ", ".join(sorted(out_of_scope))
            )


def validate_validation_object(value: Any, context: str) -> dict[str, Any]:
    obj = require_object(value, context)
    keys = {
        "mode",
        "validator_id",
        "independence_group",
        "verdict",
        "reason",
        "evidence_checked",
        "counterevidence",
        "causality",
        "root_cause_supported",
    }
    require_exact_keys(obj, keys, context)
    mode = require_string(obj["mode"], f"{context}.mode")
    verdict = require_string(obj["verdict"], f"{context}.verdict")
    causality = require_string(obj["causality"], f"{context}.causality")
    if mode not in VALIDATION_MODES:
        raise ReviewError(f"{context}.mode must be one of {sorted(VALIDATION_MODES)}")
    if verdict not in VALIDATION_VERDICTS:
        raise ReviewError(f"{context}.verdict must be one of {sorted(VALIDATION_VERDICTS)}")
    if causality not in CAUSALITIES:
        raise ReviewError(f"{context}.causality must be one of {sorted(CAUSALITIES)}")
    return {
        "mode": mode,
        "validator_id": require_string(obj["validator_id"], f"{context}.validator_id"),
        "independence_group": require_string(obj["independence_group"], f"{context}.independence_group"),
        "verdict": verdict,
        "reason": require_string(obj["reason"], f"{context}.reason"),
        "evidence_checked": require_string_array(obj["evidence_checked"], f"{context}.evidence_checked"),
        "counterevidence": require_string_array(obj["counterevidence"], f"{context}.counterevidence"),
        "causality": causality,
        "root_cause_supported": require_bool(obj["root_cause_supported"], f"{context}.root_cause_supported"),
    }


def validate_materiality_object(value: Any, context: str) -> dict[str, Any]:
    obj = require_object(value, context)
    keys = {
        "concrete_evidence",
        "plausible_negative_consequence",
        "beyond_preference",
        "current_scope_relevance",
        "improvement_current_cost",
        "improvement_benefit_exceeds_churn",
        "coverage_targets_fragile_behavior",
    }
    require_exact_keys(obj, keys, context)
    result: dict[str, Any] = {}
    for key in keys:
        raw = obj[key]
        if key in {
            "improvement_current_cost",
            "improvement_benefit_exceeds_churn",
            "coverage_targets_fragile_behavior",
        }:
            if raw is not None and not isinstance(raw, bool):
                raise ReviewError(f"{context}.{key} must be boolean or null")
            result[key] = raw
        else:
            result[key] = require_bool(raw, f"{context}.{key}")
    return result



def validate_repair_direction(
    value: Any,
    context: str,
    *,
    required: bool,
) -> dict[str, Any] | None:
    if value is None:
        if required:
            raise ReviewError(f"{context} is required for a kept finding")
        return None
    if not required:
        raise ReviewError(f"{context} must be null for a discarded finding")

    obj = require_object(value, context)
    keys = {
        "status",
        "confidence",
        "root_cause",
        "objective",
        "smallest_safe_change",
        "constraints_to_preserve",
        "state_or_exception_cases",
        "alternatives_checked",
        "required_test_evidence",
        "open_user_decisions",
        "known_limits",
    }
    require_exact_keys(obj, keys, context)

    status = require_string(obj["status"], f"{context}.status")
    confidence = require_string(obj["confidence"], f"{context}.confidence")
    if status not in REPAIR_DIRECTION_STATUSES:
        raise ReviewError(f"{context}.status is invalid")
    if confidence not in CONFIDENCES:
        raise ReviewError(f"{context}.confidence is invalid")

    constraints = require_string_array(
        obj["constraints_to_preserve"],
        f"{context}.constraints_to_preserve",
    )
    evidence = require_string_array(
        obj["required_test_evidence"],
        f"{context}.required_test_evidence",
    )
    decisions = require_string_array(
        obj["open_user_decisions"],
        f"{context}.open_user_decisions",
    )
    if not constraints or not evidence:
        raise ReviewError(f"{context} needs constraints and causal test evidence")
    if status == "needs_user_decision" and not decisions:
        raise ReviewError(f"{context} must name the user decision")

    return {
        "status": status,
        "confidence": confidence,
        "root_cause": require_string(obj["root_cause"], f"{context}.root_cause"),
        "objective": require_string(obj["objective"], f"{context}.objective"),
        "smallest_safe_change": require_string(
            obj["smallest_safe_change"],
            f"{context}.smallest_safe_change",
        ),
        "constraints_to_preserve": constraints,
        "state_or_exception_cases": require_string_array(
            obj["state_or_exception_cases"],
            f"{context}.state_or_exception_cases",
        ),
        "alternatives_checked": require_string_array(
            obj["alternatives_checked"],
            f"{context}.alternatives_checked",
        ),
        "required_test_evidence": evidence,
        "open_user_decisions": decisions,
        "known_limits": require_string_array(
            obj["known_limits"],
            f"{context}.known_limits",
        ),
    }


def validate_repair_audit(
    value: Any,
    context: str,
    *,
    required: bool,
    scope_hash: str,
    candidate_ids: list[str],
    repair_direction: dict[str, Any] | None,
    source_independence_groups: list[str],
    source_candidates: list[dict[str, Any]],
    category: str,
) -> dict[str, Any] | None:
    if value is None:
        if required:
            raise ReviewError(f"{context} is required for a kept finding")
        return None
    if not required:
        raise ReviewError(f"{context} must be null for a discarded finding")
    if repair_direction is None:
        raise ReviewError(f"{context} cannot be validated without a repair direction")

    obj = require_object(value, context)
    keys = {
        "scope_hash",
        "candidate_ids",
        "repair_direction_hash",
        "mode",
        "auditor_id",
        "independence_group",
        "trigger",
        "rationale",
        "evidence_checked",
        "counterevidence",
    }
    require_exact_keys(obj, keys, context)

    audit_scope_hash = require_sha256(obj["scope_hash"], f"{context}.scope_hash")
    if audit_scope_hash != scope_hash:
        raise ReviewError(f"{context}.scope_hash does not match the run")
    audit_candidate_ids = require_string_array(obj["candidate_ids"], f"{context}.candidate_ids")
    if audit_candidate_ids != candidate_ids:
        raise ReviewError(f"{context}.candidate_ids must exactly match the retained group")
    direction_hash = canonical_hash(repair_direction)
    audit_direction_hash = require_sha256(
        obj["repair_direction_hash"],
        f"{context}.repair_direction_hash",
    )
    if audit_direction_hash != direction_hash:
        raise ReviewError(f"{context}.repair_direction_hash does not match the normalized repair direction")

    mode = require_string(obj["mode"], f"{context}.mode")
    if mode not in VALIDATION_MODES:
        raise ReviewError(f"{context}.mode must be one of {sorted(VALIDATION_MODES)}")
    independence_group = require_string(
        obj["independence_group"],
        f"{context}.independence_group",
    )
    if mode == "independent" and independence_group in source_independence_groups:
        raise ReviewError(f"{context}: auditor is not independent from the candidate sources")

    trigger = require_string(obj["trigger"], f"{context}.trigger")
    if mode == "controller_direct":
        sensitive_categories = {"security", "privacy", "api_contract", "migration", "concurrency"}
        affected_paths = {
            path
            for candidate in source_candidates
            for path in [candidate["file"], *candidate["related_changed_files"]]
        }
        eligible = (
            trigger == "mechanically_entailed_low_risk"
            and category not in sensitive_categories
            and all(candidate["estimated_fix_risk"] == "low" for candidate in source_candidates)
            and len(affected_paths) == 1
            and repair_direction["status"] == "reviewed"
            and not repair_direction["open_user_decisions"]
        )
        if not eligible:
            raise ReviewError(
                f"{context}: controller_direct is allowed only for a mechanically entailed low-risk local correction"
            )

    return {
        "scope_hash": audit_scope_hash,
        "candidate_ids": audit_candidate_ids,
        "repair_direction_hash": audit_direction_hash,
        "mode": mode,
        "auditor_id": require_string(obj["auditor_id"], f"{context}.auditor_id"),
        "independence_group": independence_group,
        "trigger": trigger,
        "rationale": require_string(obj["rationale"], f"{context}.rationale"),
        "evidence_checked": require_string_array(
            obj["evidence_checked"],
            f"{context}.evidence_checked",
        ),
        "counterevidence": require_string_array(
            obj["counterevidence"],
            f"{context}.counterevidence",
        ),
    }

def validate_adjudication(raw: Any, *, candidates_bundle: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    obj = require_object(raw, "adjudication")
    expected_schema = expected_adjudication_schema(state)
    material_review = expected_schema == ADJUDICATION_SCHEMA_REVIEW
    top_keys = {
        "schema_version",
        "scope_hash",
        "candidate_bundle_hash",
        "adjudicator_id",
        "groups",
        "verdict",
        "summary",
        "limitations",
    }
    require_exact_keys(obj, top_keys, "adjudication")
    if obj["schema_version"] != expected_schema:
        raise ReviewError(
            "Adjudication schema_version does not match the active workflow profile: "
            f"expected {expected_schema}, got {obj['schema_version']}"
        )
    if obj["scope_hash"] != state["scope_hash"]:
        raise ReviewError("Adjudication scope_hash does not match the run")
    if obj["candidate_bundle_hash"] != candidates_bundle["candidate_bundle_hash"]:
        raise ReviewError("Adjudication candidate_bundle_hash does not match normalized candidates")
    verdict = require_string(obj["verdict"], "adjudication.verdict")
    if verdict not in MERGE_VERDICTS:
        raise ReviewError(f"adjudication.verdict must be one of {sorted(MERGE_VERDICTS)}")
    candidates_by_id = {item["candidate_id"]: item for item in candidates_bundle["candidates"]}
    groups_raw = require_array(obj["groups"], "adjudication.groups")
    groups: list[dict[str, Any]] = []
    seen_group_ids: set[str] = set()
    seen_candidate_ids: set[str] = set()
    group_keys = {
        "group_id",
        "candidate_ids",
        "canonical_title",
        "nature",
        "category",
        "severity",
        "confidence",
        "file",
        "line_start",
        "line_end",
        "evidence_side",
        "evidence_quote",
        "source_reviewers",
        "source_independence_groups",
        "validation",
        "materiality",
        "disposition",
        "decision_reason",
        "discard_reason_code",
        "recommended_action",
        "required_pre_fix_verification",
        "repair_direction",
        "repair_audit",
    }
    if material_review:
        group_keys.add("source_lenses")

    for index, raw_group in enumerate(groups_raw):
        context = f"adjudication.groups[{index}]"
        group = require_object(raw_group, context)
        require_exact_keys(group, group_keys, context)
        group_id = require_string(group["group_id"], f"{context}.group_id")
        if group_id in seen_group_ids:
            raise ReviewError(f"Duplicate adjudication group_id: {group_id}")
        seen_group_ids.add(group_id)
        candidate_ids = require_string_array(group["candidate_ids"], f"{context}.candidate_ids")
        if not candidate_ids:
            raise ReviewError(f"{context}.candidate_ids must not be empty")
        unknown = sorted(set(candidate_ids) - set(candidates_by_id))
        if unknown:
            raise ReviewError(f"{context} references unknown candidate IDs: {', '.join(unknown)}")
        overlap = sorted(set(candidate_ids) & seen_candidate_ids)
        if overlap:
            raise ReviewError(f"Candidate IDs appear in more than one group: {', '.join(overlap)}")
        seen_candidate_ids.update(candidate_ids)
        source_candidates = [candidates_by_id[item] for item in candidate_ids]

        nature = require_string(group["nature"], f"{context}.nature")
        category = require_string(group["category"], f"{context}.category")
        severity = require_string(group["severity"], f"{context}.severity")
        confidence = require_string(group["confidence"], f"{context}.confidence")
        if nature not in NATURES or category not in CATEGORIES or severity not in SEVERITIES or confidence not in CONFIDENCES:
            raise ReviewError(f"{context} contains an invalid nature/category/severity/confidence")
        file = require_canonical_repo_path(group["file"], f"{context}.file")
        line_start = require_int(group["line_start"], f"{context}.line_start", minimum=1)
        line_end = require_int(group["line_end"], f"{context}.line_end", minimum=1)
        if line_end < line_start:
            raise ReviewError(f"{context}.line_end must be >= line_start")
        evidence_side = require_string(group["evidence_side"], f"{context}.evidence_side")
        if evidence_side not in EVIDENCE_SIDES:
            raise ReviewError(f"{context}.evidence_side is invalid")
        evidence_quote = require_string(group["evidence_quote"], f"{context}.evidence_quote")

        if not any(
            candidate["file"] == file
            and candidate["line_start"] == line_start
            and candidate["line_end"] == line_end
            and candidate["evidence_side"] == evidence_side
            and candidate["evidence_quote"] == evidence_quote
            and candidate["nature"] == nature
            and candidate["category"] == category
            for candidate in source_candidates
        ):
            raise ReviewError(f"{context}: canonical evidence/nature/category must be inherited from a source candidate")

        expected_reviewers = sorted({candidate["reviewer_id"] for candidate in source_candidates})
        expected_groups = sorted({candidate["independence_group"] for candidate in source_candidates})
        source_reviewers = sorted(require_string_array(group["source_reviewers"], f"{context}.source_reviewers"))
        source_independence = sorted(
            require_string_array(group["source_independence_groups"], f"{context}.source_independence_groups")
        )
        if source_reviewers != expected_reviewers:
            raise ReviewError(f"{context}.source_reviewers must exactly match candidate sources")
        if source_independence != expected_groups:
            raise ReviewError(f"{context}.source_independence_groups must exactly match candidate sources")
        source_lenses: list[str] | None = None
        if material_review:
            expected_lenses = sorted({candidate["lens_id"] for candidate in source_candidates})
            source_lenses = require_string_array(
                group["source_lenses"], f"{context}.source_lenses"
            )
            if source_lenses != expected_lenses:
                raise ReviewError(
                    f"{context}.source_lenses must be the exact sorted candidate-source lenses"
                )

        validation = validate_validation_object(group["validation"], f"{context}.validation")
        if validation["mode"] == "independent" and validation["independence_group"] in expected_groups:
            raise ReviewError(f"{context}: validator is not independent from the candidate sources")
        materiality = validate_materiality_object(group["materiality"], f"{context}.materiality")
        disposition = require_string(group["disposition"], f"{context}.disposition")
        if disposition not in DISPOSITIONS:
            raise ReviewError(f"{context}.disposition must be keep or discard")
        discard_reason = group["discard_reason_code"]
        if discard_reason is not None:
            discard_reason = require_string(discard_reason, f"{context}.discard_reason_code")
            if discard_reason not in DISCARD_REASONS:
                raise ReviewError(f"{context}.discard_reason_code is invalid")
        recommendation = require_string(group["recommended_action"], f"{context}.recommended_action")
        if recommendation not in RECOMMENDATIONS:
            raise ReviewError(f"{context}.recommended_action is invalid")
        required_pre_fix = group["required_pre_fix_verification"]
        if required_pre_fix is not None:
            required_pre_fix = require_string(required_pre_fix, f"{context}.required_pre_fix_verification")
        repair_direction = validate_repair_direction(
            group["repair_direction"],
            f"{context}.repair_direction",
            required=disposition == "keep",
        )
        repair_audit = validate_repair_audit(
            group["repair_audit"],
            f"{context}.repair_audit",
            required=disposition == "keep",
            scope_hash=state["scope_hash"],
            candidate_ids=candidate_ids,
            repair_direction=repair_direction,
            source_independence_groups=source_independence,
            source_candidates=source_candidates,
            category=category,
        )

        if disposition == "keep":
            if discard_reason is not None:
                raise ReviewError(f"{context}: kept group must have null discard_reason_code")
            for key in (
                "concrete_evidence",
                "plausible_negative_consequence",
                "beyond_preference",
                "current_scope_relevance",
            ):
                if materiality[key] is not True:
                    raise ReviewError(f"{context}: kept group failed materiality gate {key}")
            if not validation["root_cause_supported"]:
                raise ReviewError(f"{context}: kept group lacks root-cause support")
            if validation["verdict"] == "rejected":
                raise ReviewError(f"{context}: validator-rejected group cannot be kept")
            if validation["verdict"] == "uncertain":
                if severity not in {"blocker", "high"} or not required_pre_fix:
                    raise ReviewError(
                        f"{context}: uncertain findings may be kept only at blocker/high with required_pre_fix_verification"
                    )
            if validation["causality"] == "pre_existing" and not any(c["direct_dependency"] for c in source_candidates):
                raise ReviewError(f"{context}: unrelated pre-existing group cannot be kept")
            if nature == "improvement":
                if materiality["improvement_current_cost"] is not True:
                    raise ReviewError(f"{context}: improvement lacks demonstrated current cost")
                if materiality["improvement_benefit_exceeds_churn"] is not True:
                    raise ReviewError(f"{context}: improvement benefit does not exceed churn")
            if nature == "coverage_gap" and materiality["coverage_targets_fragile_behavior"] is not True:
                raise ReviewError(f"{context}: coverage gap does not target fragile material behavior")
            if recommendation == "none":
                raise ReviewError(f"{context}: kept group must have an actionable recommendation")
        else:
            if discard_reason is None:
                raise ReviewError(f"{context}: discarded group requires discard_reason_code")

        normalized_group = {
            "group_id": group_id,
            "candidate_ids": candidate_ids,
            "canonical_title": require_string(group["canonical_title"], f"{context}.canonical_title"),
            "nature": nature,
            "category": category,
            "severity": severity,
            "confidence": confidence,
            "file": file,
            "line_start": line_start,
            "line_end": line_end,
            "evidence_side": evidence_side,
            "evidence_quote": evidence_quote,
            "source_reviewers": source_reviewers,
            "source_independence_groups": source_independence,
            "validation": validation,
            "materiality": materiality,
            "disposition": disposition,
            "decision_reason": require_string(group["decision_reason"], f"{context}.decision_reason"),
            "discard_reason_code": discard_reason,
            "recommended_action": recommendation,
            "required_pre_fix_verification": required_pre_fix,
            "repair_direction": repair_direction,
            "repair_direction_hash": canonical_hash(repair_direction) if repair_direction is not None else None,
            "repair_audit": repair_audit,
        }
        if source_lenses is not None:
            normalized_group["source_lenses"] = source_lenses
        groups.append(normalized_group)

    missing = sorted(set(candidates_by_id) - seen_candidate_ids)
    if missing:
        raise ReviewError(f"Adjudication omitted candidate IDs: {', '.join(missing)}")

    kept = [group for group in groups if group["disposition"] == "keep"]
    if not kept and verdict != "READY":
        raise ReviewError("A ledger with no kept findings must use verdict READY")
    if kept and verdict == "READY":
        raise ReviewError("READY is valid only when the ledger has no kept findings")
    if verdict == "READY WITH OPTIONAL FOLLOW-UPS" and (
        any(group["severity"] in {"blocker", "high"} for group in kept)
        or any(group["recommended_action"] == "fix_now" for group in kept)
    ):
        raise ReviewError("READY WITH OPTIONAL FOLLOW-UPS cannot contain blocker/high or fix-now findings")
    if any(group["severity"] == "blocker" for group in kept) and verdict != "NOT READY":
        raise ReviewError("A kept blocker finding requires verdict NOT READY")
    if any(group["severity"] == "high" or group["recommended_action"] == "fix_now" for group in kept):
        if verdict not in {"SHOULD FIX BEFORE MERGE", "NOT READY"}:
            raise ReviewError("High/fix-now findings require SHOULD FIX BEFORE MERGE or NOT READY")

    return {
        "schema_version": expected_schema,
        "scope_hash": state["scope_hash"],
        "candidate_bundle_hash": candidates_bundle["candidate_bundle_hash"],
        "adjudicator_id": require_string(obj["adjudicator_id"], "adjudication.adjudicator_id"),
        "groups": groups,
        "verdict": verdict,
        "summary": require_string(obj["summary"], "adjudication.summary"),
        "limitations": require_string_array(obj["limitations"], "adjudication.limitations"),
    }


def require_compatible_existing_adjudicated_authority(
    run_dir: Path,
    state: dict[str, Any],
    *,
    candidates_bundle: dict[str, Any],
) -> None:
    try:
        persisted_adjudication = require_object(
            load_json(run_dir / "adjudication.normalized.json"),
            "normalized adjudication",
        )
        validation_input = copy.deepcopy(persisted_adjudication)
        for index, raw_group in enumerate(
            require_array(validation_input.get("groups"), "normalized adjudication.groups")
        ):
            group = require_object(raw_group, f"normalized adjudication.groups[{index}]")
            group.pop("repair_direction_hash", None)
        normalized_adjudication = validate_adjudication(
            validation_input,
            candidates_bundle=candidates_bundle,
            state=state,
        )
        if persisted_adjudication != normalized_adjudication:
            raise ReviewError(
                "Existing normalized adjudication does not match its canonical profile"
            )
        load_verified_ledger(run_dir, state)
    except ReviewError as exc:
        raise ReviewError(
            "Existing normalized adjudication or ledger authority is incompatible with "
            "the active workflow profile; start a new run. Cause: " + str(exc)
        ) from exc


def validate_test_spec(value: Any, context: str, repo: Path) -> dict[str, Any]:
    obj = require_object(value, context)
    keys = {"id", "command", "working_directory", "required", "timeout_seconds", "purpose"}
    require_exact_keys(obj, keys, context)
    working_directory = normalize_repo_path(
        require_string(obj["working_directory"], f"{context}.working_directory", nonempty=False), allow_dot=True
    )
    workdir_path = repo if working_directory == "." else repo_path(repo, working_directory)
    if not workdir_path.exists() or not workdir_path.is_dir():
        raise ReviewError(f"{context}.working_directory does not exist as a directory: {working_directory}")
    test_id = require_string(obj["id"], f"{context}.id")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", test_id):
        raise ReviewError(f"{context}.id must be a safe artifact identifier without slashes or traversal")
    return {
        "id": test_id,
        "command": require_string(obj["command"], f"{context}.command"),
        "working_directory": working_directory,
        "required": require_bool(obj["required"], f"{context}.required"),
        "timeout_seconds": require_int(obj["timeout_seconds"], f"{context}.timeout_seconds", minimum=1, maximum=3600),
        "purpose": require_string(obj["purpose"], f"{context}.purpose"),
    }


def validate_direction_handling(
    value: Any,
    context: str,
    *,
    expected_sources: list[str],
) -> list[dict[str, str]]:
    entries = require_array(value, context)
    normalized: list[dict[str, str]] = []
    sources: list[str] = []
    for index, raw_entry in enumerate(entries):
        entry_context = f"{context}[{index}]"
        entry = require_object(raw_entry, entry_context)
        require_exact_keys(entry, {"source", "handling"}, entry_context)
        source = require_string(entry["source"], f"{entry_context}.source")
        sources.append(source)
        normalized.append(
            {
                "source": source,
                "handling": require_string(entry["handling"], f"{entry_context}.handling"),
            }
        )
    if sources != expected_sources:
        raise ReviewError(f"{context} must cover each approved direction entry exactly and in order")
    return normalized


def validate_repair_direction_assessment(
    value: Any,
    context: str,
    *,
    finding: dict[str, Any],
) -> dict[str, Any]:
    obj = require_object(value, context)
    keys = {
        "repair_direction_hash",
        "constraint_handling",
        "state_or_exception_handling",
        "open_user_decision_handling",
        "alternatives_considered",
        "diverges",
        "divergence_rationale",
    }
    require_exact_keys(obj, keys, context)
    direction = require_object(finding.get("repair_direction"), f"ledger {finding['finding_id']}.repair_direction")
    expected_hash = require_sha256(
        finding.get("repair_direction_hash"),
        f"ledger {finding['finding_id']}.repair_direction_hash",
    )
    if expected_hash != canonical_hash(direction):
        raise ReviewError(f"Ledger direction hash is invalid for {finding['finding_id']}")
    direction_hash = require_sha256(obj["repair_direction_hash"], f"{context}.repair_direction_hash")
    if direction_hash != expected_hash:
        raise ReviewError(f"{context}.repair_direction_hash does not match the approved ledger direction")

    alternatives = require_string_array(
        obj["alternatives_considered"],
        f"{context}.alternatives_considered",
    )
    if not alternatives:
        raise ReviewError(f"{context}.alternatives_considered must not be empty")
    diverges = require_bool(obj["diverges"], f"{context}.diverges")
    rationale = obj["divergence_rationale"]
    if diverges:
        rationale = require_string(rationale, f"{context}.divergence_rationale")
    elif rationale is not None:
        raise ReviewError(f"{context}.divergence_rationale must be null when diverges is false")

    return {
        "repair_direction_hash": direction_hash,
        "constraint_handling": validate_direction_handling(
            obj["constraint_handling"],
            f"{context}.constraint_handling",
            expected_sources=direction["constraints_to_preserve"],
        ),
        "state_or_exception_handling": validate_direction_handling(
            obj["state_or_exception_handling"],
            f"{context}.state_or_exception_handling",
            expected_sources=direction["state_or_exception_cases"],
        ),
        "open_user_decision_handling": validate_direction_handling(
            obj["open_user_decision_handling"],
            f"{context}.open_user_decision_handling",
            expected_sources=direction["open_user_decisions"],
        ),
        "alternatives_considered": alternatives,
        "diverges": diverges,
        "divergence_rationale": rationale,
    }


def validate_fix_plan(
    raw: Any,
    *,
    repo: Path,
    state: dict[str, Any],
    findings_gate: dict[str, Any],
    ledger: dict[str, Any],
) -> dict[str, Any]:
    obj = require_object(raw, "fix plan")
    top_keys = {
        "schema_version",
        "scope_hash",
        "findings_gate_hash",
        "plan_summary",
        "items",
        "global_tests",
        "no_unrelated_cleanup",
        "no_new_improvements_during_fix",
        "post_fix_review_scope",
        "scope_expansion_policy",
        "max_repair_rounds",
    }
    require_exact_keys(obj, top_keys, "fix plan")
    if obj["schema_version"] != FIX_PLAN_SCHEMA:
        raise ReviewError("Unsupported fix-plan schema_version")
    if obj["scope_hash"] != state["scope_hash"]:
        raise ReviewError("Fix plan scope_hash does not match the run")
    if obj["findings_gate_hash"] != findings_gate["receipt_hash"]:
        raise ReviewError("Fix plan findings_gate_hash does not match Gate A")
    if obj["no_unrelated_cleanup"] is not True:
        raise ReviewError("Fix plan must set no_unrelated_cleanup=true")
    if obj["no_new_improvements_during_fix"] is not True:
        raise ReviewError("Fix plan must set no_new_improvements_during_fix=true")
    if obj["post_fix_review_scope"] != "approved_findings_and_fix_introduced_regressions_only":
        raise ReviewError("Fix plan has an invalid post_fix_review_scope")
    if obj["scope_expansion_policy"] != "restore_and_reapprove":
        raise ReviewError("Fix plan must require restore_and_reapprove for scope expansion")
    max_repair_rounds = require_int(obj["max_repair_rounds"], "fix plan.max_repair_rounds", minimum=0, maximum=2)

    approved_ids = set(findings_gate["decisions"]["approved"])
    if not approved_ids:
        raise ReviewError("Gate A approved no findings; no fix plan is permitted")
    items_raw = require_array(obj["items"], "fix plan.items")
    items: list[dict[str, Any]] = []
    item_ids: set[str] = set()
    findings_by_id = {finding["finding_id"]: finding for finding in ledger["findings"]}
    item_keys = {
        "finding_id",
        "root_cause",
        "objective",
        "repair_direction_assessment",
        "depends_on",
        "steps",
        "allowed_paths",
        "tests",
        "manual_verification",
        "rollback_strategy",
        "risk_controls",
        "success_evidence",
        "max_attempts",
    }
    for index, raw_item in enumerate(items_raw):
        context = f"fix plan.items[{index}]"
        item = require_object(raw_item, context)
        require_exact_keys(item, item_keys, context)
        finding_id = require_string(item["finding_id"], f"{context}.finding_id")
        if finding_id in item_ids:
            raise ReviewError(f"Duplicate plan item for {finding_id}")
        item_ids.add(finding_id)
        finding = findings_by_id.get(finding_id)
        if finding is None:
            raise ReviewError(f"{context}.finding_id does not exist in the Gate-A ledger")
        direction_assessment = validate_repair_direction_assessment(
            item["repair_direction_assessment"],
            f"{context}.repair_direction_assessment",
            finding=finding,
        )
        depends_on = require_string_array(item["depends_on"], f"{context}.depends_on")
        if finding_id in depends_on:
            raise ReviewError(f"{context}: finding cannot depend on itself")
        steps = require_string_array(item["steps"], f"{context}.steps", unique=False)
        if not steps:
            raise ReviewError(f"{context}.steps must not be empty")
        allowed_paths = [normalize_repo_path(path) for path in require_string_array(item["allowed_paths"], f"{context}.allowed_paths")]
        if not allowed_paths:
            raise ReviewError(f"{context}.allowed_paths must not be empty")
        for allowed_path in allowed_paths:
            target = repo_path(repo, allowed_path)
            if target.exists() and target.is_dir() and not target.is_symlink():
                raise ReviewError(
                    f"{context}.allowed_paths must name exact files or symlinks, not directories: {allowed_path}"
                )
        tests = [validate_test_spec(value, f"{context}.tests[{test_index}]", repo) for test_index, value in enumerate(require_array(item["tests"], f"{context}.tests"))]
        test_ids = [test["id"] for test in tests]
        if len(test_ids) != len(set(test_ids)):
            raise ReviewError(f"{context}.tests contains duplicate IDs")
        manual_verification = require_string_array(item["manual_verification"], f"{context}.manual_verification")
        if not any(test["required"] for test in tests) and not manual_verification:
            raise ReviewError(f"{context} needs a required automated test or manual verification evidence")
        items.append(
            {
                "finding_id": finding_id,
                "root_cause": require_string(item["root_cause"], f"{context}.root_cause"),
                "objective": require_string(item["objective"], f"{context}.objective"),
                "repair_direction_assessment": direction_assessment,
                "depends_on": depends_on,
                "steps": steps,
                "allowed_paths": allowed_paths,
                "tests": tests,
                "manual_verification": manual_verification,
                "rollback_strategy": require_string(item["rollback_strategy"], f"{context}.rollback_strategy"),
                "risk_controls": require_string_array(item["risk_controls"], f"{context}.risk_controls"),
                "success_evidence": require_string_array(item["success_evidence"], f"{context}.success_evidence"),
                "max_attempts": require_int(item["max_attempts"], f"{context}.max_attempts", minimum=1, maximum=3),
            }
        )

    if item_ids != approved_ids:
        missing = sorted(approved_ids - item_ids)
        extra = sorted(item_ids - approved_ids)
        details: list[str] = []
        if missing:
            details.append(f"missing approved IDs {', '.join(missing)}")
        if extra:
            details.append(f"contains unapproved IDs {', '.join(extra)}")
        raise ReviewError("Fix plan item set is not exact: " + "; ".join(details))
    for item in items:
        invalid_dependencies = sorted(set(item["depends_on"]) - approved_ids)
        if invalid_dependencies:
            raise ReviewError(
                f"Plan item {item['finding_id']} depends on unapproved IDs: {', '.join(invalid_dependencies)}"
            )

    graph = {item["finding_id"]: set(item["depends_on"]) for item in items}
    temporary: set[str] = set()
    permanent: set[str] = set()

    def visit(node: str) -> None:
        if node in permanent:
            return
        if node in temporary:
            raise ReviewError("Fix plan dependency graph contains a cycle")
        temporary.add(node)
        for dependency in graph[node]:
            visit(dependency)
        temporary.remove(node)
        permanent.add(node)

    for node in graph:
        visit(node)

    global_tests = [
        validate_test_spec(value, f"fix plan.global_tests[{index}]", repo)
        for index, value in enumerate(require_array(obj["global_tests"], "fix plan.global_tests"))
    ]
    global_ids = [test["id"] for test in global_tests]
    if len(global_ids) != len(set(global_ids)):
        raise ReviewError("fix plan.global_tests contains duplicate IDs")

    return {
        "schema_version": FIX_PLAN_SCHEMA,
        "scope_hash": state["scope_hash"],
        "findings_gate_hash": findings_gate["receipt_hash"],
        "plan_summary": require_string(obj["plan_summary"], "fix plan.plan_summary"),
        "items": items,
        "global_tests": global_tests,
        "no_unrelated_cleanup": True,
        "no_new_improvements_during_fix": True,
        "post_fix_review_scope": "approved_findings_and_fix_introduced_regressions_only",
        "scope_expansion_policy": "restore_and_reapprove",
        "max_repair_rounds": max_repair_rounds,
    }


def render_candidates_markdown(bundle: dict[str, Any], rejections: list[dict[str, Any]]) -> str:
    material_review_bundle = (
        bundle.get("schema_version") == NORMALIZED_CANDIDATES_SCHEMA_REVIEW
    )
    candidate_count_label = (
        "candidate_records" if material_review_bundle else "Candidates accepted"
    )
    lines = [
        "# Candidate ingestion",
        "",
        f"- Scope hash: `{bundle['scope_hash']}`",
        f"- Candidate bundle hash: `{bundle['candidate_bundle_hash']}`",
        f"- Reviewer sets accepted: `{len(bundle['reviewer_sets'])}`",
        f"- {candidate_count_label}: `{len(bundle['candidates'])}`",
    ]
    if material_review_bundle:
        completed_atomic_checks = sum(
            len(reviewer_set["check_results"])
            for reviewer_set in bundle["reviewer_sets"]
        )
        lines.append(f"- completed_atomic_checks: `{completed_atomic_checks}`")
    lines.extend(
        [
            f"- Candidate/input rejections: `{len(rejections)}`",
            "",
            "## Candidate records" if material_review_bundle else "## Accepted candidates",
            "",
        ]
    )
    if not bundle["candidates"]:
        lines.append("- none")
    for candidate in bundle["candidates"]:
        lens = (
            f"lens `{candidate['lens_id']}`, "
            if "lens_id" in candidate
            else ""
        )
        lines.append(
            f"- **{candidate['candidate_id']}** [{candidate['severity']}/{candidate['confidence']}] "
            f"`{candidate['file']}:{candidate['line_start']}` — {candidate['title']} "
            f"({lens}reviewer `{candidate['reviewer_id']}`, "
            f"group `{candidate['independence_group']}`)"
        )
    lines.extend(["", "## Rejected reviewer output", ""])
    if not rejections:
        lines.append("- none")
    for item in rejections:
        location = f" index {item['index']}" if "index" in item else ""
        lines.append(f"- `{item['source_file']}`{location}: {item['reason']}")
    return "\n".join(lines) + "\n"


def representative_candidate(group: dict[str, Any], candidates_by_id: dict[str, dict[str, Any]]) -> dict[str, Any]:
    for candidate_id in group["candidate_ids"]:
        candidate = candidates_by_id[candidate_id]
        if (
            candidate["file"] == group["file"]
            and candidate["line_start"] == group["line_start"]
            and candidate["evidence_quote"] == group["evidence_quote"]
        ):
            return candidate
    return candidates_by_id[group["candidate_ids"][0]]


def render_ledger_markdown(ledger: dict[str, Any]) -> str:
    lines = [
        "# Material review ledger",
        "",
        "## Merge-readiness decision",
        "",
        ledger["verdict"],
        "",
        "## Frozen scope",
        "",
        f"- Scope hash: `{ledger['scope_hash']}`",
        f"- Candidate bundle hash: `{ledger['candidate_bundle_hash']}`",
        f"- Ledger hash: `{ledger['ledger_hash']}`",
        "",
        "## Summary",
        "",
        ledger["summary"],
        "",
        "## Kept material findings",
        "",
        "Gate A approves findings for repair planning only. It does not approve the provisional repair direction or authorize edits.",
        "",
    ]
    if not ledger["findings"]:
        lines.append("No material findings survived adjudication.")
    for finding in ledger["findings"]:
        lines.extend(
            [
                f"### {finding['finding_id']} — {finding['title']}",
                "",
                f"- Category / nature: `{finding['category']}` / `{finding['nature']}`",
                f"- Severity / confidence: `{finding['severity']}` / `{finding['confidence']}`",
                f"- Evidence: `{finding['file']}:{finding['line_start']}-{finding['line_end']}` "
                f"({finding['evidence_side']}) — `{finding['evidence_quote']}`",
                f"- Consequence: {finding['observable_consequence']}",
                f"- Trigger: {finding['trigger_conditions']}",
                f"- Validation: `{finding['validation']['mode']}` / `{finding['validation']['verdict']}` — "
                f"{finding['validation']['reason']}",
                f"- Why material: {finding['decision_reason']}",
                f"- Fix risk: `{finding['estimated_fix_risk']}`",
                f"- Recommendation: `{finding['recommended_action']}`",
                f"- Candidate sources: {', '.join(finding['candidate_ids'])}",
            ]
        )
        if "source_lenses" in finding:
            lines.append(f"- Source lenses: {', '.join(finding['source_lenses'])}")
        direction = finding["repair_direction"]
        lines.extend(
            [
                "- Provisional repair direction:",
                f"  - Direction hash: `{finding['repair_direction_hash']}`",
                f"  - Status / confidence: `{direction['status']}` / `{direction['confidence']}`",
                f"  - Root cause: {direction['root_cause']}",
                f"  - Objective: {direction['objective']}",
                f"  - Smallest safe change: {direction['smallest_safe_change']}",
            ]
        )
        detail_fields = (
            ("Constraints to preserve", "constraints_to_preserve"),
            ("States and exceptions", "state_or_exception_cases"),
            ("Alternatives checked", "alternatives_checked"),
            ("Required test evidence", "required_test_evidence"),
            ("Open user decisions", "open_user_decisions"),
            ("Known limits", "known_limits"),
        )
        for label, key in detail_fields:
            if direction[key]:
                lines.append(f"  - {label}:")
                lines.extend(f"    - {value}" for value in direction[key])
        audit = finding["repair_audit"]
        lines.extend(
            [
                "- Repair-direction audit:",
                f"  - Mode / auditor / independence group: `{audit['mode']}` / "
                f"`{audit['auditor_id']}` / `{audit['independence_group']}`",
                f"  - Trigger: `{audit['trigger']}`",
                f"  - Rationale: {audit['rationale']}",
            ]
        )
        if audit["evidence_checked"]:
            lines.append("  - Evidence checked:")
            lines.extend(f"    - {value}" for value in audit["evidence_checked"])
        if audit["counterevidence"]:
            lines.append("  - Counterevidence:")
            lines.extend(f"    - {value}" for value in audit["counterevidence"])
        if finding["required_pre_fix_verification"]:
            lines.append(f"- Required pre-fix verification: {finding['required_pre_fix_verification']}")
        lines.append("")
    lines.extend(["## Discarded candidates", ""])
    if not ledger["discarded"]:
        lines.append("- none")
    for group in ledger["discarded"]:
        lens_suffix = (
            f"; lenses {', '.join(group['source_lenses'])}"
            if "source_lenses" in group
            else ""
        )
        lines.append(
            f"- **{group['group_id']}** ({', '.join(group['candidate_ids'])}{lens_suffix}) — "
            f"{group['canonical_title']} "
            f"-> `{group['discard_reason_code']}`: {group['decision_reason']}"
        )
    if ledger["limitations"]:
        lines.extend(["", "## Coverage limitations", ""])
        lines.extend(f"- {item}" for item in ledger["limitations"])
    return "\n".join(lines) + "\n"


def render_plan_markdown(plan: dict[str, Any]) -> str:
    lines = [
        "# Gate-B repair plan",
        "",
        f"- Scope hash: `{plan['scope_hash']}`",
        f"- Findings gate hash: `{plan['findings_gate_hash']}`",
        f"- Plan hash: `{plan['plan_hash']}`",
        f"- Max repair rounds: `{plan['max_repair_rounds']}`",
        "",
        "## Summary",
        "",
        plan["plan_summary"],
        "",
        "## Finding plans",
        "",
    ]
    for item in plan["items"]:
        lines.extend(
            [
                f"### {item['finding_id']}",
                "",
                f"- Root cause: {item['root_cause']}",
                f"- Objective: {item['objective']}",
                f"- Approved direction hash: `{item['repair_direction_assessment']['repair_direction_hash']}`",
                f"- Dependencies: {', '.join(item['depends_on']) if item['depends_on'] else 'none'}",
                f"- Allowed paths: {', '.join(f'`{path}`' for path in item['allowed_paths'])}",
                f"- Max attempts: `{item['max_attempts']}`",
            ]
        )
        assessment = item["repair_direction_assessment"]
        lines.append("- Repair-direction assessment:")
        handling_fields = (
            ("Constraints", "constraint_handling"),
            ("States and exceptions", "state_or_exception_handling"),
            ("Open user decisions", "open_user_decision_handling"),
        )
        for label, key in handling_fields:
            lines.append(f"  - {label}:")
            if not assessment[key]:
                lines.append("    - none")
            for entry in assessment[key]:
                lines.append(f"    - {entry['source']} -> {entry['handling']}")
        lines.append("  - Alternatives considered:")
        lines.extend(f"    - {entry}" for entry in assessment["alternatives_considered"])
        lines.append(f"  - Diverges from approved direction: `{str(assessment['diverges']).lower()}`")
        if assessment["divergence_rationale"]:
            lines.append(f"  - Divergence rationale: {assessment['divergence_rationale']}")
        lines.append("- Steps:")
        lines.extend(f"  {index}. {step}" for index, step in enumerate(item["steps"], start=1))
        lines.append("- Tests:")
        if not item["tests"]:
            lines.append("  - none")
        for test in item["tests"]:
            lines.append(
                f"  - `{test['id']}` ({'required' if test['required'] else 'optional'}, {test['timeout_seconds']}s) "
                f"from `{test['working_directory']}`: `{test['command']}` — {test['purpose']}"
            )
        if item["manual_verification"]:
            lines.append("- Manual verification:")
            lines.extend(f"  - {entry}" for entry in item["manual_verification"])
        lines.append(f"- Rollback: {item['rollback_strategy']}")
        if item["risk_controls"]:
            lines.append("- Risk controls:")
            lines.extend(f"  - {entry}" for entry in item["risk_controls"])
        lines.append("")
    lines.extend(["## Global tests", ""])
    if not plan["global_tests"]:
        lines.append("- none")
    for test in plan["global_tests"]:
        lines.append(
            f"- `{test['id']}` ({'required' if test['required'] else 'optional'}, {test['timeout_seconds']}s) "
            f"from `{test['working_directory']}`: `{test['command']}` — {test['purpose']}"
        )
    lines.extend(
        [
            "",
            "## Loop and scope controls",
            "",
            "- Unrelated cleanup: prohibited",
            "- New improvements during repair: prohibited",
            "- Post-fix review: approved findings and fix-introduced regressions only",
            "- Scope expansion: restore and obtain a new Gate B approval",
        ]
    )
    return "\n".join(lines) + "\n"


def command_init(args: argparse.Namespace) -> int:
    repo = resolve_repo_root(args.repo_root)
    artifact_root = resolve_artifact_root(repo, args.artifact_root)
    run_id = normalize_run_id(args.run_id) if args.run_id else make_run_id()
    runs_root = artifact_root / "runs"
    run_dir = runs_root / run_id

    # Freeze the Git scope before creating any artifact directory. This avoids
    # contaminating the scope when a caller supplies an invalid in-worktree
    # location and leaves no half-initialized run when scope resolution fails.
    scope = build_scope(
        repo,
        requested_scope=args.scope,
        base_ref=args.base,
        head_ref=args.head,
        include_untracked=not args.exclude_untracked,
    )
    workflow_profile = getattr(args, "_workflow_profile", WORKFLOW_PROFILE_REVIEW)
    if workflow_profile not in {WORKFLOW_PROFILE_REVIEW, SIMPLIFICATION_PROFILE}:
        raise ReviewError(f"Unsupported internal workflow profile: {workflow_profile}")
    temp_run_dir = runs_root / f".{run_id}.initializing-{uuid.uuid4().hex[:8]}"
    runs_authority = RunArtifactAuthority(runs_root, create=True)
    with active_artifact_authority(runs_authority):
        if artifact_exists(run_dir):
            raise ReviewError(f"Run already exists: {run_dir}")
        artifact_mkdir(temp_run_dir, parents=False, exist_ok=False)
        try:
            limitations = snapshot_sources(
                repo,
                temp_run_dir,
                scope,
                max_file_bytes=args.max_snapshot_file_bytes,
                max_total_bytes=args.max_snapshot_total_bytes,
            )
            write_source_bundle_files(temp_run_dir, scope, limitations)
            identity = scope["identity"]
            state = {
                "schema_version": (
                    MATERIAL_REVIEW_STATE_SCHEMA
                    if workflow_profile == WORKFLOW_PROFILE_REVIEW
                    else SIMPLIFICATION_STATE_SCHEMA
                ),
                "tool_version": TOOL_VERSION,
                "run_id": run_id,
                "repo_root": str(repo),
                "artifact_root": str(artifact_root),
                "phase": PHASE_CONTEXT,
                "created_at": utc_now(),
                "updated_at": utc_now(),
                "scope_hash": scope["scope_hash"],
                "scope_params": {
                    "actual_scope": identity["actual_scope"],
                    "base_reference": identity["base_reference"],
                    "head_reference": identity.get("head_reference"),
                    "include_untracked": identity["include_untracked"],
                },
                "mutation_allowed": identity["mutable"],
                "hashes": {},
                "gates": {},
                "approved_findings": [],
                "finding_status": {},
                "global_test_results": {},
                "active_finding": None,
                "repair_round": 0,
                "repair_targets": [],
                "expected_workspace_guard_hash": None,
                "pre_fix_checkpoint": None,
                "events": [
                    {
                        "at": utc_now(),
                        "event": "scope_frozen",
                        "scope_hash": scope["scope_hash"],
                    }
                ],
            }
            if workflow_profile == WORKFLOW_PROFILE_REVIEW:
                state["workflow_profile"] = WORKFLOW_PROFILE_REVIEW
                state["coverage_required"] = True
            else:
                state["profile"] = SIMPLIFICATION_PROFILE
            save_state(temp_run_dir, state)
            artifact_rename(temp_run_dir, run_dir)
        except BaseException:
            artifact_remove(temp_run_dir, recursive=True, missing_ok=True)
            raise

    print(f"[OK] Frozen review scope: {scope['scope_hash']}")
    print(f"Run ID: {run_id}")
    print(f"Artifact directory: {run_dir}")
    print(f"Mode: {identity['actual_scope']}")
    print(f"Changed files: {len(identity['files'])}")
    print(f"Mutation aligned: {str(identity['mutable']).lower()}")
    return 0


def command_record_coverage(args: argparse.Namespace) -> int:
    repo = resolve_repo_root(args.repo_root)
    _, run_dir = resolve_run_dir(args, repo)
    state = load_state(run_dir)
    if state["phase"] != PHASE_CONTEXT:
        raise ReviewError(f"Cannot record coverage in phase {state['phase']}")
    require_current_material_review_contract(state)
    check_scope_fresh(repo, run_dir, state)
    scope_identity = load_verified_scope(run_dir, state)["identity"]
    allowed_context_paths = discover_comparison_context_paths(repo, scope_identity)
    plan = validate_coverage_plan(
        load_json(Path(args.input).expanduser().resolve()),
        run_dir=run_dir,
        state=state,
        allowed_context_paths=allowed_context_paths,
    )
    context_paths = collect_coverage_context_paths(plan)
    existing_hash = state["hashes"].get("coverage_plan_hash")
    if existing_hash:
        existing = load_recorded_coverage_plan(run_dir, state)
        live_context, _ = _build_coverage_context(
            repo,
            run_dir,
            scope_identity,
            context_paths,
            max_files=32,
            max_file_bytes=2 * 1024 * 1024,
            max_total_bytes=25 * 1024 * 1024,
        )
        live_context_hash = canonical_hash(live_context)
        plan_hash = canonical_hash(
            {"plan": plan, "coverage_context_hash": live_context_hash}
        )
        if (
            existing == plan
            and existing_hash == plan_hash
            and state["hashes"].get("coverage_context_hash") == live_context_hash
        ):
            print(f"[OK] Coverage plan already recorded: {existing_hash}")
            return 0
        raise ReviewError("Coverage plan is already recorded; start a new run to change it")
    if (
        "coverage_context_hash" in state["hashes"]
        or artifact_exists(run_dir / "coverage-plan.json")
        or artifact_exists(run_dir / "coverage-context.json")
        or artifact_exists(run_dir / "coverage-context")
    ):
        raise ReviewError(
            "Coverage artifacts exist without valid state bindings; start a new run"
        )
    context = snapshot_coverage_context(
        repo,
        run_dir,
        scope_identity,
        context_paths,
    )
    context_hash = context["coverage_context_hash"]
    plan_hash = canonical_hash({"plan": plan, "coverage_context_hash": context_hash})
    artifact = {
        **plan,
        "coverage_context_hash": context_hash,
        "coverage_plan_hash": plan_hash,
    }
    atomic_write_json(run_dir / "coverage-context.json", context)
    atomic_write_json(run_dir / "coverage-plan.json", artifact)
    state["hashes"]["coverage_context_hash"] = context_hash
    state["hashes"]["coverage_plan_hash"] = plan_hash
    state["events"].append(
        {
            "at": utc_now(),
            "event": "coverage_plan_recorded",
            "coverage_plan_hash": plan_hash,
            "coverage_context_hash": context_hash,
        }
    )
    save_state(run_dir, state)
    print(f"[OK] Coverage plan recorded: {plan_hash}")
    return 0


def command_check_scope(args: argparse.Namespace) -> int:
    repo = resolve_repo_root(args.repo_root)
    _, run_dir = resolve_run_dir(args, repo)
    state = load_state(run_dir)
    current = check_scope_fresh(repo, run_dir, state)
    print(f"[OK] Scope is fresh: {current['scope_hash']}")
    print(f"Run ID: {state['run_id']}")
    return 0


def command_ingest_material_review_candidates(
    args: argparse.Namespace, *, repo: Path, run_dir: Path, state: dict[str, Any]
) -> int:
    sources = [Path(raw).expanduser().resolve() for raw in args.input]
    input_hashes: list[str] = []
    reviewer_sets: list[dict[str, Any]] = []
    rejections: list[dict[str, Any]] = []
    try:
        plan = load_recorded_coverage_plan(run_dir, state)
        for source in sources:
            try:
                input_hashes.append(sha256_file(source))
                normalized_set, finding_rejections = validate_candidate_set(
                    load_json(source),
                    source_file=source,
                    repo=repo,
                    run_dir=run_dir,
                    state=state,
                    plan=plan,
                )
                reviewer_sets.append(normalized_set)
                rejections.extend(finding_rejections)
            except ReviewError as exc:
                rejections.append({"source_file": str(source), "reason": str(exc)})
        if rejections:
            raise ReviewError("Candidate ingestion failed: " + "; ".join(item["reason"] for item in rejections))
        validate_candidate_wave_against_coverage(plan, reviewer_sets)
        allowed_paths = all_scope_paths(load_verified_scope(run_dir, state)["identity"])
        allowed_paths.update(collect_coverage_context_paths(plan))
        validate_material_review_coverage_paths(
            reviewer_sets, allowed_paths=allowed_paths
        )
        for reviewer_set in reviewer_sets:
            for finding in reviewer_set["findings"]:
                finding["lens_id"] = reviewer_set["lens_id"]
                finding["assignment_id"] = reviewer_set["assignment_id"]
    except ReviewError as exc:
        if not rejections or rejections[-1].get("reason") != str(exc):
            rejections.append({"reason": str(exc)})
        failure = {
            "schema_version": "material-review/candidate-ingestion-failure/v1",
            "scope_hash": state["scope_hash"],
            "coverage_plan_hash": state["hashes"]["coverage_plan_hash"],
            "coverage_context_hash": state["hashes"]["coverage_context_hash"],
            "input_hashes": input_hashes,
            "rejections": rejections,
        }
        atomic_write_json(run_dir / "candidate-ingestion-failure.json", failure)
        raise

    reviewer_sets.sort(
        key=lambda item: (
            item["assignment_id"],
            item["lens_id"],
            item["reviewer_id"],
            item["independence_group"],
            item["review_mode"],
        )
    )
    candidates: list[dict[str, Any]] = []
    for reviewer_set in reviewer_sets:
        candidates.extend(reviewer_set.pop("findings"))
    for candidate in candidates:
        candidate.pop("source_file", None)
    candidates.sort(
        key=lambda item: (
            item["reviewer_id"],
            item["independence_group"],
            item["local_id"],
            item["file"],
            item["line_start"],
            item["lens_id"],
            item["assignment_id"],
        )
    )
    for index, candidate in enumerate(candidates, start=1):
        candidate["candidate_id"] = f"C{index:03d}"

    local_to_candidate = {
        (candidate["assignment_id"], candidate["local_id"]): candidate["candidate_id"]
        for candidate in candidates
    }
    for reviewer_set in reviewer_sets:
        for check_result in reviewer_set["check_results"]:
            local_ids = check_result.pop("finding_local_ids")
            check_result["candidate_ids"] = sorted(
                {
                    local_to_candidate[(reviewer_set["assignment_id"], local_id)]
                    for local_id in local_ids
                }
            )

    payload = {
        "schema_version": NORMALIZED_CANDIDATES_SCHEMA_REVIEW,
        "scope_hash": state["scope_hash"],
        "coverage_plan_hash": state["hashes"]["coverage_plan_hash"],
        "coverage_context_hash": state["hashes"]["coverage_context_hash"],
        "reviewer_sets": reviewer_sets,
        "candidates": candidates,
        "rejections": rejections,
    }
    bundle_hash = canonical_hash(payload)

    with candidate_authority_lock(run_dir):
        state = load_state(run_dir)
        require_current_material_review_contract(state)
        if state["phase"] not in {PHASE_CONTEXT, PHASE_CANDIDATES}:
            raise ReviewError(f"Cannot ingest candidates in phase {state['phase']}")
        check_scope_fresh(repo, run_dir, state)
        load_recorded_coverage_plan(run_dir, state)
        if (
            state["scope_hash"] != payload["scope_hash"]
            or state["hashes"]["coverage_plan_hash"]
            != payload["coverage_plan_hash"]
            or state["hashes"]["coverage_context_hash"]
            != payload["coverage_context_hash"]
        ):
            raise ReviewError(
                "Candidate authority inputs changed before publication; rerun validation"
            )

        if state["phase"] == PHASE_CANDIDATES:
            existing = require_compatible_existing_candidate_authority(run_dir, state)
            if existing["candidate_bundle_hash"] == bundle_hash:
                print(f"[OK] Candidate bundle already captured: {bundle_hash}")
                print("Exact validated retry made no changes")
                return 0
            raise ReviewError(
                "Candidate bundle is already captured and differs from this complete valid "
                "wave; start a new run"
            )

        payload["candidate_bundle_hash"] = bundle_hash
        payload["generated_at"] = utc_now()
        atomic_write_json(run_dir / "candidates.json", payload)
        atomic_write_json(run_dir / "candidate-rejections.json", rejections)
        atomic_write_text(
            run_dir / "candidates.md",
            render_candidates_markdown(payload, rejections),
        )

        state["phase"] = PHASE_CANDIDATES
        state["hashes"]["candidate_bundle_hash"] = bundle_hash
        state["events"].append(
            {
                "at": utc_now(),
                "event": "candidates_ingested",
                "reviewer_sets": len(reviewer_sets),
                "candidates": len(candidates),
                "rejections": len(rejections),
                "candidate_bundle_hash": bundle_hash,
            }
        )
        save_state(run_dir, state)
    print(f"[OK] Candidate bundle written: {bundle_hash}")
    print(f"Accepted reviewer sets: {len(reviewer_sets)}")
    print(f"Accepted candidates: {len(candidates)}")
    print(f"Rejected candidate/input records: {len(rejections)}")
    print(f"Artifact: {run_dir / 'candidates.md'}")
    return 0


def command_ingest_candidates(args: argparse.Namespace) -> int:
    repo = resolve_repo_root(args.repo_root)
    _, run_dir = resolve_run_dir(args, repo)
    state = load_state(run_dir)
    if state["phase"] not in {PHASE_CONTEXT, PHASE_CANDIDATES}:
        raise ReviewError(f"Cannot ingest candidates in phase {state['phase']}")
    check_scope_fresh(repo, run_dir, state)
    if not args.input:
        raise ReviewError("At least one --input candidate JSON file is required")
    if not is_simplification_state(state):
        require_current_material_review_contract(state)
        if "coverage_plan_hash" not in state["hashes"]:
            raise ReviewError("Coverage plan is not recorded")
        return command_ingest_material_review_candidates(args, repo=repo, run_dir=run_dir, state=state)

    if state["phase"] == PHASE_CANDIDATES:
        require_compatible_existing_candidate_authority(run_dir, state)

    reviewer_sets: list[dict[str, Any]] = []
    rejections: list[dict[str, Any]] = []
    for raw_path in args.input:
        source = Path(raw_path).expanduser().resolve()
        try:
            normalized_set, finding_rejections = validate_candidate_set(
                load_json(source), source_file=source, repo=repo, run_dir=run_dir, state=state
            )
            reviewer_sets.append(normalized_set)
            rejections.extend(finding_rejections)
        except ReviewError as exc:
            rejections.append({"source_file": str(source), "reason": str(exc)})
    if not reviewer_sets:
        atomic_write_json(run_dir / "candidate-rejections.json", rejections)
        raise ReviewError("All candidate-set inputs were rejected; review coverage is not valid")

    candidates: list[dict[str, Any]] = []
    for reviewer_set in reviewer_sets:
        candidates.extend(reviewer_set.pop("findings"))
    candidates.sort(
        key=lambda item: (
            item["reviewer_id"],
            item["independence_group"],
            item["local_id"],
            item["file"],
            item["line_start"],
        )
    )
    for index, candidate in enumerate(candidates, start=1):
        candidate["candidate_id"] = f"C{index:03d}"

    payload = {
        "schema_version": NORMALIZED_CANDIDATES_SCHEMA_SIMPLIFICATION,
        "scope_hash": state["scope_hash"],
        "reviewer_sets": reviewer_sets,
        "candidates": candidates,
        "rejections": rejections,
    }
    bundle_hash = canonical_hash(payload)
    payload["candidate_bundle_hash"] = bundle_hash
    payload["generated_at"] = utc_now()
    atomic_write_json(run_dir / "candidates.json", payload)
    atomic_write_json(run_dir / "candidate-rejections.json", rejections)
    atomic_write_text(run_dir / "candidates.md", render_candidates_markdown(payload, rejections))

    state["phase"] = PHASE_CANDIDATES
    state["hashes"]["candidate_bundle_hash"] = bundle_hash
    state["events"].append(
        {
            "at": utc_now(),
            "event": "candidates_ingested",
            "reviewer_sets": len(reviewer_sets),
            "candidates": len(candidates),
            "rejections": len(rejections),
            "candidate_bundle_hash": bundle_hash,
        }
    )
    save_state(run_dir, state)
    print(f"[OK] Candidate bundle written: {bundle_hash}")
    print(f"Accepted reviewer sets: {len(reviewer_sets)}")
    print(f"Accepted candidates: {len(candidates)}")
    print(f"Rejected candidate/input records: {len(rejections)}")
    print(f"Artifact: {run_dir / 'candidates.md'}")
    return 0


def command_compile_ledger(args: argparse.Namespace) -> int:
    repo = resolve_repo_root(args.repo_root)
    _, run_dir = resolve_run_dir(args, repo)
    state = load_state(run_dir)
    if state["phase"] not in {PHASE_CANDIDATES, PHASE_ADJUDICATED}:
        raise ReviewError(f"Cannot compile ledger in phase {state['phase']}")
    check_scope_fresh(repo, run_dir, state)
    material_review = not is_simplification_state(state)
    if material_review:
        require_current_material_review_contract(state)
        load_recorded_coverage_plan(run_dir, state)
    candidates_bundle = load_verified_candidates_bundle(run_dir, state)
    if state["phase"] == PHASE_ADJUDICATED:
        require_compatible_existing_adjudicated_authority(
            run_dir,
            state,
            candidates_bundle=candidates_bundle,
        )
    adjudication = validate_adjudication(load_json(Path(args.input).expanduser().resolve()), candidates_bundle=candidates_bundle, state=state)
    candidates_by_id = {item["candidate_id"]: item for item in candidates_bundle["candidates"]}
    kept_groups = [group for group in adjudication["groups"] if group["disposition"] == "keep"]
    kept_groups.sort(
        key=lambda group: (
            SEVERITY_ORDER[group["severity"]],
            CONFIDENCE_ORDER[group["confidence"]],
            group["file"],
            group["line_start"],
            group["canonical_title"],
        )
    )
    findings: list[dict[str, Any]] = []
    for index, group in enumerate(kept_groups, start=1):
        representative = representative_candidate(group, candidates_by_id)
        finding = {
            "finding_id": f"F{index:03d}",
            "group_id": group["group_id"],
            "candidate_ids": group["candidate_ids"],
            "title": group["canonical_title"],
            "nature": group["nature"],
            "category": group["category"],
            "severity": group["severity"],
            "confidence": group["confidence"],
            "file": group["file"],
            "line_start": group["line_start"],
            "line_end": group["line_end"],
            "evidence_side": group["evidence_side"],
            "evidence_quote": group["evidence_quote"],
            "observable_consequence": representative["observable_consequence"],
            "trigger_conditions": representative["trigger_conditions"],
            "repair_direction": group["repair_direction"],
            "repair_direction_hash": group["repair_direction_hash"],
            "repair_audit": group["repair_audit"],
            "estimated_fix_risk": representative["estimated_fix_risk"],
            "requires_user_decision": bool(group["repair_direction"]["open_user_decisions"]),
            "assumptions": representative["assumptions"],
            "source_reviewers": group["source_reviewers"],
            "source_independence_groups": group["source_independence_groups"],
            "validation": group["validation"],
            "materiality": group["materiality"],
            "decision_reason": group["decision_reason"],
            "recommended_action": group["recommended_action"],
            "required_pre_fix_verification": group["required_pre_fix_verification"],
        }
        if material_review:
            finding["source_lenses"] = group["source_lenses"]
        findings.append(finding)
    discarded = [group for group in adjudication["groups"] if group["disposition"] == "discard"]
    payload = {
        "schema_version": expected_ledger_schema(state),
        "scope_hash": state["scope_hash"],
        "candidate_bundle_hash": candidates_bundle["candidate_bundle_hash"],
        "adjudicator_id": adjudication["adjudicator_id"],
        "verdict": adjudication["verdict"],
        "summary": adjudication["summary"],
        "findings": findings,
        "discarded": discarded,
        "limitations": adjudication["limitations"],
    }
    ledger_hash = canonical_hash(payload)
    payload["ledger_hash"] = ledger_hash
    payload["generated_at"] = utc_now()
    atomic_write_json(run_dir / "ledger.json", payload)
    atomic_write_text(run_dir / "ledger.md", render_ledger_markdown(payload))
    atomic_write_json(run_dir / "adjudication.normalized.json", adjudication)

    state["phase"] = PHASE_ADJUDICATED
    state["hashes"]["ledger_hash"] = ledger_hash
    state["events"].append(
        {
            "at": utc_now(),
            "event": "ledger_compiled",
            "ledger_hash": ledger_hash,
            "kept": len(findings),
            "discarded": len(discarded),
            "verdict": payload["verdict"],
        }
    )
    save_state(run_dir, state)
    print(f"[OK] Ledger compiled: {ledger_hash}")
    print(f"Kept findings: {len(findings)}")
    print(f"Discarded candidate groups: {len(discarded)}")
    print(f"Verdict: {payload['verdict']}")
    print(f"Gate A artifact: {run_dir / 'ledger.md'}")
    return 0


def command_gate_findings(args: argparse.Namespace) -> int:
    repo = resolve_repo_root(args.repo_root)
    _, run_dir = resolve_run_dir(args, repo)
    state = load_state(run_dir)
    if state["phase"] != PHASE_ADJUDICATED:
        raise ReviewError(f"Gate A requires phase {PHASE_ADJUDICATED}; current phase is {state['phase']}")
    check_scope_fresh(repo, run_dir, state)
    ledger = load_verified_ledger(run_dir, state)
    finding_ids = {item["finding_id"] for item in ledger["findings"]}
    approved = parse_csv_ids(args.approve)
    rejected = parse_csv_ids(args.reject)
    deferred = parse_csv_ids(args.defer)
    if approved & rejected or approved & deferred or rejected & deferred:
        raise ReviewError("Gate A approve/reject/defer sets must be disjoint")
    user_statement = require_string(args.user_statement, "--user-statement")
    if finding_ids:
        if args.accept_empty:
            raise ReviewError("--accept-empty is valid only when the ledger kept no findings")
        disposition_ids = approved | rejected | deferred
        if disposition_ids != finding_ids:
            missing = sorted(finding_ids - disposition_ids)
            extra = sorted(disposition_ids - finding_ids)
            details: list[str] = []
            if missing:
                details.append(f"missing dispositions for {', '.join(missing)}")
            if extra:
                details.append(f"unknown IDs {', '.join(extra)}")
            raise ReviewError("Gate A must dispose every kept finding exactly once: " + "; ".join(details))
    else:
        if not args.accept_empty:
            raise ReviewError("The empty material set still requires --accept-empty and a user statement")
        if approved or rejected or deferred:
            raise ReviewError("No finding IDs may be supplied when accepting an empty material set")

    receipt_payload = {
        "schema_version": FINDINGS_GATE_SCHEMA,
        "run_id": state["run_id"],
        "scope_hash": state["scope_hash"],
        "ledger_hash": ledger["ledger_hash"],
        "decisions": {
            "approved": sorted(approved),
            "rejected": sorted(rejected),
            "deferred": sorted(deferred),
            "accepted_empty": bool(args.accept_empty),
        },
        "user_statement": user_statement,
        "recorded_at": utc_now(),
    }
    receipt_hash = canonical_hash(receipt_payload)
    receipt_payload["receipt_hash"] = receipt_hash
    gates_dir = run_dir / "gates"
    atomic_write_json(gates_dir / "findings.json", receipt_payload)
    state["gates"]["findings"] = receipt_hash
    state["approved_findings"] = sorted(approved)
    state["hashes"]["findings_gate_hash"] = receipt_hash
    state["events"].append(
        {
            "at": utc_now(),
            "event": "gate_a_recorded",
            "receipt_hash": receipt_hash,
            "approved": sorted(approved),
            "rejected": sorted(rejected),
            "deferred": sorted(deferred),
        }
    )
    if approved:
        state["phase"] = PHASE_FINDINGS_APPROVED
    else:
        state["phase"] = PHASE_COMPLETE
        if not finding_ids:
            completion_message = "No material improvements recommended."
        else:
            completion_message = (
                "No findings were approved for repair. The material findings and merge-readiness "
                "decision remain recorded in the ledger."
            )
        atomic_write_text(
            run_dir / "completion.md",
            "# Review complete\n\n"
            f"{completion_message}\n\n"
            f"- Gate A receipt: `{receipt_hash}`\n"
            f"- Ledger: `{ledger['ledger_hash']}`\n"
            f"- Ledger verdict: `{ledger['verdict']}`\n"
            f"- Rejected by user: `{', '.join(sorted(rejected)) if rejected else 'none'}`\n"
            f"- Deferred by user: `{', '.join(sorted(deferred)) if deferred else 'none'}`\n",
        )
    save_state(run_dir, state)
    print(f"[OK] Gate A recorded: {receipt_hash}")
    print(f"Approved: {', '.join(sorted(approved)) if approved else 'none'}")
    print(f"Rejected: {', '.join(sorted(rejected)) if rejected else 'none'}")
    print(f"Deferred: {', '.join(sorted(deferred)) if deferred else 'none'}")
    print(f"Next phase: {state['phase']}")
    return 0


def command_validate_plan(args: argparse.Namespace) -> int:
    repo = resolve_repo_root(args.repo_root)
    _, run_dir = resolve_run_dir(args, repo)
    state = load_state(run_dir)
    if state["phase"] not in {PHASE_FINDINGS_APPROVED, PHASE_PLAN_VALIDATED}:
        raise ReviewError(f"Cannot validate a plan in phase {state['phase']}")
    check_scope_fresh(repo, run_dir, state)
    findings_gate = load_verified_findings_gate(run_dir, state)
    ledger = load_verified_ledger(run_dir, state, findings_gate=findings_gate)
    plan = validate_fix_plan(
        load_json(Path(args.input).expanduser().resolve()),
        repo=repo,
        state=state,
        findings_gate=findings_gate,
        ledger=ledger,
    )
    plan_hash = canonical_hash(plan)
    plan["plan_hash"] = plan_hash
    plan["validated_at"] = utc_now()
    atomic_write_json(run_dir / "fix-plan.json", plan)
    atomic_write_text(run_dir / "fix-plan.md", render_plan_markdown(plan))
    old_gate = run_dir / "gates" / "plan.json"
    if artifact_exists(old_gate):
        archive = run_dir / "gates" / "archive"
        artifact_mkdir(archive, parents=True, exist_ok=True)
        artifact_rename(
            old_gate,
            archive / f"plan-{utc_now().replace(':', '')}.json",
        )
    state["phase"] = PHASE_PLAN_VALIDATED
    state["hashes"]["plan_hash"] = plan_hash
    state["gates"].pop("plan", None)
    state["events"].append(
        {
            "at": utc_now(),
            "event": "plan_validated",
            "plan_hash": plan_hash,
            "items": len(plan["items"]),
        }
    )
    save_state(run_dir, state)
    print(f"[OK] Repair plan validated: {plan_hash}")
    print(f"Plan items: {len(plan['items'])}")
    print(f"Gate B artifact: {run_dir / 'fix-plan.md'}")
    return 0


def command_gate_plan(args: argparse.Namespace) -> int:
    repo = resolve_repo_root(args.repo_root)
    _, run_dir = resolve_run_dir(args, repo)
    state = load_state(run_dir)
    if state["phase"] != PHASE_PLAN_VALIDATED:
        raise ReviewError(f"Gate B requires phase {PHASE_PLAN_VALIDATED}; current phase is {state['phase']}")
    check_scope_fresh(repo, run_dir, state)
    if args.approve == args.reject:
        raise ReviewError("Specify exactly one of --approve or --reject")
    user_statement = require_string(args.user_statement, "--user-statement")
    plan = load_verified_plan(run_dir, state)
    findings_gate = load_verified_findings_gate(run_dir, state)
    receipt_payload = {
        "schema_version": PLAN_GATE_SCHEMA,
        "run_id": state["run_id"],
        "scope_hash": state["scope_hash"],
        "findings_gate_hash": findings_gate["receipt_hash"],
        "plan_hash": plan["plan_hash"],
        "approved": bool(args.approve),
        "user_statement": user_statement,
        "recorded_at": utc_now(),
    }
    receipt_hash = canonical_hash(receipt_payload)
    receipt_payload["receipt_hash"] = receipt_hash
    atomic_write_json(run_dir / "gates" / "plan.json", receipt_payload)
    state["events"].append(
        {
            "at": utc_now(),
            "event": "gate_b_recorded",
            "receipt_hash": receipt_hash,
            "plan_hash": plan["plan_hash"],
            "approved": bool(args.approve),
        }
    )
    if args.approve:
        state["phase"] = PHASE_PLAN_APPROVED
        state["gates"]["plan"] = receipt_hash
        state["hashes"]["plan_gate_hash"] = receipt_hash
    else:
        state["phase"] = PHASE_FINDINGS_APPROVED
        state["gates"].pop("plan", None)
        state["hashes"].pop("plan_gate_hash", None)
    save_state(run_dir, state)
    print(f"[OK] Gate B recorded: {receipt_hash}")
    print(f"Decision: {'approved' if args.approve else 'rejected'}")
    print(f"Next phase: {state['phase']}")
    return 0


def plan_item_by_id(plan: dict[str, Any], finding_id: str) -> dict[str, Any]:
    for item in plan["items"]:
        if item["finding_id"] == finding_id:
            return item
    raise ReviewError(f"Finding {finding_id} is not present in the approved plan")


def test_by_id(tests: list[dict[str, Any]], test_id: str, context: str) -> dict[str, Any]:
    for test in tests:
        if test["id"] == test_id:
            return test
    raise ReviewError(f"Unknown {context} test ID: {test_id}")


def command_begin_fix(args: argparse.Namespace) -> int:
    repo = resolve_repo_root(args.repo_root)
    _, run_dir = resolve_run_dir(args, repo)
    state = load_state(run_dir)
    if state["phase"] != PHASE_PLAN_APPROVED:
        raise ReviewError(f"begin-fix requires phase {PHASE_PLAN_APPROVED}; current phase is {state['phase']}")
    check_scope_fresh(repo, run_dir, state)
    if not state["mutation_allowed"]:
        raise ReviewError("The reviewed scope is not aligned with the working tree; reinitialize a mutable local scope before repair")
    plan = load_verified_plan(run_dir, state)
    plan_gate = load_verified_plan_gate(run_dir, state)
    if not plan_gate["approved"] or plan_gate["plan_hash"] != plan["plan_hash"]:
        raise ReviewError("Gate B receipt does not authorize the current plan")
    allowed_paths = sorted({path for item in plan["items"] for path in item["allowed_paths"]})
    checkpoint_dir = run_dir / "checkpoints" / "pre-fix"
    metadata = create_checkpoint(repo, checkpoint_dir, allowed_paths)
    finding_status = {
        item["finding_id"]: {
            "status": "pending",
            "attempts": 0,
            "max_attempts": item["max_attempts"],
            "history": [],
        }
        for item in plan["items"]
    }
    state["phase"] = PHASE_FIXING
    state["pre_fix_checkpoint"] = str(checkpoint_dir.relative_to(run_dir)).replace("\\", "/")
    state["hashes"]["pre_fix_snapshot_hash"] = metadata["checkpoint_hash"]
    state["finding_status"] = finding_status
    state["active_finding"] = None
    state["global_test_results"] = {}
    state["repair_round"] = 0
    state["repair_targets"] = []
    state["expected_workspace_guard_hash"] = metadata["workspace_guard"]["guard_hash"]
    state["events"].append(
        {
            "at": utc_now(),
            "event": "fix_layer_started",
            "pre_fix_snapshot_hash": metadata["checkpoint_hash"],
            "allowed_paths": allowed_paths,
        }
    )
    save_state(run_dir, state)
    print(f"[OK] Repair layer started from checkpoint {metadata['checkpoint_hash']}")
    print(f"Approved findings: {', '.join(state['approved_findings'])}")
    print("No staging, commits, branch changes, or unapproved paths are authorized.")
    return 0


def validate_finding_start(state: dict[str, Any], plan: dict[str, Any], finding_id: str) -> dict[str, Any]:
    if finding_id not in state["approved_findings"]:
        raise ReviewError(f"Finding {finding_id} was not approved at Gate A")
    item = plan_item_by_id(plan, finding_id)
    status = state["finding_status"].get(finding_id)
    if not status:
        raise ReviewError(f"Missing internal status for {finding_id}")
    if status["status"] not in {"pending", "repair_pending"}:
        raise ReviewError(f"Finding {finding_id} is not pending (status {status['status']})")
    if status["attempts"] >= status["max_attempts"]:
        raise ReviewError(f"Finding {finding_id} exhausted its approved attempt budget")
    for dependency in item["depends_on"]:
        if state["finding_status"][dependency]["status"] != "fixed":
            raise ReviewError(f"Finding {finding_id} depends on {dependency}, which is not fixed")
    return item


def command_start_finding(args: argparse.Namespace) -> int:
    repo = resolve_repo_root(args.repo_root)
    _, run_dir = resolve_run_dir(args, repo)
    state = load_state(run_dir)
    if state["phase"] != PHASE_FIXING:
        raise ReviewError(f"start-finding requires phase {PHASE_FIXING}; current phase is {state['phase']}")
    if state["active_finding"] is not None:
        raise ReviewError(f"Another finding is active: {state['active_finding']['finding_id']}")
    plan = load_verified_plan(run_dir, state)
    item = validate_finding_start(state, plan, args.finding)
    current = ensure_expected_workspace(repo, state)
    status = state["finding_status"][args.finding]
    attempt = status["attempts"] + 1
    checkpoint_dir = run_dir / "checkpoints" / args.finding / f"attempt-{attempt}"
    metadata = create_checkpoint(repo, checkpoint_dir, item["allowed_paths"])
    status["attempts"] = attempt
    status["status"] = "active"
    state["active_finding"] = {
        "finding_id": args.finding,
        "attempt": attempt,
        "checkpoint": str(checkpoint_dir.relative_to(run_dir)).replace("\\", "/"),
        "before_guard": current,
        "allowed_paths": item["allowed_paths"],
        "test_results": {},
        "manual_evidence": [],
        "started_at": utc_now(),
    }
    state["events"].append(
        {
            "at": utc_now(),
            "event": "finding_attempt_started",
            "finding_id": args.finding,
            "attempt": attempt,
            "checkpoint_hash": metadata["checkpoint_hash"],
        }
    )
    save_state(run_dir, state)
    print(f"[OK] Started {args.finding} attempt {attempt}")
    print(f"Allowed paths: {', '.join(item['allowed_paths'])}")
    print(f"Checkpoint: {checkpoint_dir}")
    return 0


def active_boundary_audit(repo: Path, state: dict[str, Any]) -> tuple[dict[str, Any], set[str], set[str]]:
    active = state.get("active_finding")
    if not active:
        raise ReviewError("No active finding checkpoint")
    before = active["before_guard"]
    current = workspace_guard(repo)
    before_identity = before["identity"]
    current_identity = current["identity"]
    if current_identity["head_sha"] != before_identity["head_sha"]:
        raise ReviewError("HEAD changed during the finding attempt; commits/rebases are not authorized")
    if current_identity["branch"] != before_identity["branch"]:
        raise ReviewError("Branch changed during the finding attempt")
    if current_identity["staged_patch_sha256"] != before_identity["staged_patch_sha256"]:
        raise ReviewError("Git index changed during the finding attempt; staging is not authorized")
    changed_paths = diff_guard_paths(before, current)
    allowed = set(active["allowed_paths"])
    outside = changed_paths - allowed
    return current, changed_paths, outside


def terminate_process_tree(process: subprocess.Popen[bytes]) -> None:
    """Terminate a timed-out shell and its descendants as safely as the host permits."""
    if process.poll() is not None:
        return
    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGTERM)
            process.wait(timeout=2)
            return
        except (ProcessLookupError, subprocess.TimeoutExpired):
            pass
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    elif os.name == "nt":
        # /T includes descendants. Fall back to killing the direct shell if
        # taskkill is unavailable or denied.
        try:
            run_process(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                cwd=Path.cwd(),
                check=False,
            )
        except ReviewError:
            pass
        if process.poll() is None:
            process.kill()
    else:
        process.kill()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def execute_test_command(
    *,
    repo: Path,
    run_dir: Path,
    command: str,
    working_directory: str,
    timeout_seconds: int,
    log_relative: Path,
) -> dict[str, Any]:
    cwd = repo if working_directory == "." else repo_path(repo, working_directory)
    started_at = utc_now()
    timed_out = False
    exit_code: int | None
    popen_options: dict[str, Any] = {}
    if os.name == "posix":
        popen_options["start_new_session"] = True
    elif os.name == "nt":
        popen_options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP

    with tempfile.TemporaryFile(mode="w+b") as stdout_handle, tempfile.TemporaryFile(mode="w+b") as stderr_handle:
        try:
            process = subprocess.Popen(
                command,
                cwd=str(cwd),
                shell=True,
                stdout=stdout_handle,
                stderr=stderr_handle,
                env={
                    **os.environ,
                    "PYTHONDONTWRITEBYTECODE": os.environ.get("PYTHONDONTWRITEBYTECODE", "1"),
                },
                **popen_options,
            )
        except OSError as exc:
            raise ReviewError(f"Could not start approved test command: {exc}") from exc

        try:
            process.wait(timeout=timeout_seconds)
            exit_code = process.returncode
        except subprocess.TimeoutExpired:
            timed_out = True
            terminate_process_tree(process)
            exit_code = None

        finished_at = utc_now()
        log_path = run_dir / log_relative
        header = (
            f"Command: {command}\n"
            f"Working directory: {working_directory}\n"
            f"Timeout seconds: {timeout_seconds}\n"
            f"Started: {started_at}\n"
            f"Finished: {finished_at}\n"
            f"Timed out: {str(timed_out).lower()}\n"
            f"Exit code: {exit_code if exit_code is not None else 'timeout'}\n"
            "\n--- STDOUT ---\n"
        ).encode("utf-8")
        stdout_handle.seek(0)
        stderr_handle.seek(0)
        log_bytes = (
            header
            + stdout_handle.read()
            + b"\n--- STDERR ---\n"
            + stderr_handle.read()
        )
        atomic_write_bytes(log_path, log_bytes)

    return {
        "command": command,
        "working_directory": working_directory,
        "timeout_seconds": timeout_seconds,
        "started_at": started_at,
        "finished_at": finished_at,
        "timed_out": timed_out,
        "exit_code": exit_code,
        "log_path": str(log_path.relative_to(run_dir)).replace("\\", "/"),
        "log_sha256": sha256_file(log_path),
    }

def command_run_test(args: argparse.Namespace) -> int:
    repo = resolve_repo_root(args.repo_root)
    _, run_dir = resolve_run_dir(args, repo)
    state = load_state(run_dir)
    if state["phase"] != PHASE_FIXING or not state.get("active_finding"):
        raise ReviewError("run-test requires an active finding in FIXING phase")
    active = state["active_finding"]
    if active["finding_id"] != args.finding:
        raise ReviewError(f"Active finding is {active['finding_id']}, not {args.finding}")
    plan = load_verified_plan(run_dir, state)
    item = plan_item_by_id(plan, args.finding)
    test = test_by_id(item["tests"], args.test, f"{args.finding}")
    _, _, outside_before = active_boundary_audit(repo, state)
    if outside_before:
        raise ReviewError("Unapproved paths changed before test execution: " + ", ".join(sorted(outside_before)))

    prior_runs = active["test_results"].get(args.test, [])
    run_number = len(prior_runs) + 1
    test_checkpoint_dir = (
        run_dir / "checkpoints" / "tests" / args.finding / args.test / f"run-{run_number}"
    )
    test_checkpoint = create_checkpoint(repo, test_checkpoint_dir, active["allowed_paths"])
    result = execute_test_command(
        repo=repo,
        run_dir=run_dir,
        command=test["command"],
        working_directory=test["working_directory"],
        timeout_seconds=test["timeout_seconds"],
        log_relative=Path("tests") / args.finding / args.test / f"run-{run_number}.log",
    )

    after_authority = repository_authority(repo)
    after_test = after_authority["identity"]["workspace_guard"]
    before_authority = test_checkpoint["repository_authority"]
    before_test = before_authority["identity"]["workspace_guard"]
    changed_by_test = diff_guard_paths(before_test, after_test)
    control_mutations = repository_control_mutations(
        before_authority, after_authority
    )

    result["changed_paths_by_test"] = sorted(changed_by_test)
    result["control_mutations_by_test"] = control_mutations
    result["restored_after_mutation"] = False
    if changed_by_test or control_mutations:
        # A test is evidence, not an implicit edit step. Restore the exact
        # pre-test state even when the mutation stayed within approved paths.
        restored_authority = restore_checkpoint(
            repo,
            test_checkpoint_dir,
            expected_post=after_authority,
        )
        result["restored_after_mutation"] = True
        after_test = restored_authority["identity"]["workspace_guard"]

    current, changed_paths, outside_after = active_boundary_audit(repo, state)
    result["workspace_guard_hash"] = current["guard_hash"]
    result["allowed_paths_hash"] = path_subset_hash(repo, active["allowed_paths"])
    result["changed_paths_at_completion"] = sorted(changed_paths)
    result["boundary_violations"] = sorted(outside_after)
    active["test_results"].setdefault(args.test, []).append(result)
    state["events"].append(
        {
            "at": utc_now(),
            "event": "finding_test_run",
            "finding_id": args.finding,
            "test_id": args.test,
            "exit_code": result["exit_code"],
            "timed_out": result["timed_out"],
            "changed_paths_by_test": result["changed_paths_by_test"],
            "control_mutations_by_test": result["control_mutations_by_test"],
            "boundary_violations": result["boundary_violations"],
        }
    )
    save_state(run_dir, state)
    passed = (
        result["exit_code"] == 0
        and not result["timed_out"]
        and not outside_after
        and not changed_by_test
        and not control_mutations
    )
    print(f"[{'OK' if passed else 'FAIL'}] Test {args.test}")
    print(f"Exit code: {result['exit_code'] if result['exit_code'] is not None else 'timeout'}")
    print(f"Log: {run_dir / result['log_path']}")
    if changed_by_test or control_mutations:
        details = []
        if changed_by_test:
            details.append("paths: " + ", ".join(sorted(changed_by_test)))
        if control_mutations:
            details.append("controls: " + ", ".join(control_mutations))
        raise ReviewError("Approved test mutated the workspace and was restored (" + "; ".join(details) + ")")
    if outside_after:
        raise ReviewError("Test or active attempt changed unapproved paths: " + ", ".join(sorted(outside_after)))
    if result["timed_out"] or result["exit_code"] != 0:
        return 1
    return 0

def command_finish_finding(args: argparse.Namespace) -> int:
    repo = resolve_repo_root(args.repo_root)
    _, run_dir = resolve_run_dir(args, repo)
    state = load_state(run_dir)
    if state["phase"] != PHASE_FIXING or not state.get("active_finding"):
        raise ReviewError("finish-finding requires an active finding in FIXING phase")
    active = state["active_finding"]
    if active["finding_id"] != args.finding:
        raise ReviewError(f"Active finding is {active['finding_id']}, not {args.finding}")
    if args.status not in {"fixed", "blocked"}:
        raise ReviewError("--status must be fixed or blocked")
    note = require_string(args.note, "--note")
    plan = load_verified_plan(run_dir, state)
    item = plan_item_by_id(plan, args.finding)
    current, changed_paths, outside = active_boundary_audit(repo, state)
    if outside:
        raise ReviewError("Cannot retain attempt; unapproved paths changed: " + ", ".join(sorted(outside)))

    checkpoint_dir = run_dir / active["checkpoint"]
    status_record = state["finding_status"][args.finding]
    if args.status == "blocked":
        if changed_paths:
            raise ReviewError("A blocked finding must first be restored with rollback-finding")
        status_record["status"] = "blocked"
        status_record["history"].append(
            {
                "attempt": active["attempt"],
                "outcome": "blocked",
                "note": note,
                "at": utc_now(),
            }
        )
        state["active_finding"] = None
        state["phase"] = PHASE_BLOCKED
        state["expected_workspace_guard_hash"] = current["guard_hash"]
        save_state(run_dir, state)
        print(f"[BLOCKED] {args.finding}: {note}")
        return 0

    if not changed_paths and not args.allow_no_change:
        raise ReviewError("A fixed finding must have a repair delta; use --allow-no-change only with explicit evidence")

    missing_or_stale_tests: list[str] = []
    for test in item["tests"]:
        if not test["required"]:
            continue
        runs = active["test_results"].get(test["id"], [])
        if not runs:
            missing_or_stale_tests.append(f"{test['id']} (not run)")
            continue
        latest = runs[-1]
        if latest["timed_out"] or latest["exit_code"] != 0:
            missing_or_stale_tests.append(f"{test['id']} (failed)")
        elif latest.get("allowed_paths_hash") != path_subset_hash(repo, item["allowed_paths"]):
            missing_or_stale_tests.append(f"{test['id']} (stale after later edits to approved paths)")
        elif latest["boundary_violations"]:
            missing_or_stale_tests.append(f"{test['id']} (boundary violation)")
    if missing_or_stale_tests:
        raise ReviewError("Required tests are not current and passing: " + ", ".join(missing_or_stale_tests))
    manual_evidence = [item.strip() for item in (args.manual_evidence or []) if item.strip()]
    if item["manual_verification"] and not manual_evidence:
        raise ReviewError("The approved plan requires --manual-evidence before this finding can be retained")

    patch_text = render_checkpoint_diff(checkpoint_dir, repo, changed_paths)
    fix_dir = run_dir / "fixes" / args.finding / f"attempt-{active['attempt']}"
    atomic_write_text(fix_dir / "fix.patch", patch_text)
    attempt_payload = {
        "finding_id": args.finding,
        "attempt": active["attempt"],
        "outcome": "fixed",
        "changed_paths": sorted(changed_paths),
        "tests": active["test_results"],
        "manual_evidence": manual_evidence,
        "note": note,
        "workspace_guard_hash": current["guard_hash"],
        "fix_patch": str((fix_dir / "fix.patch").relative_to(run_dir)).replace("\\", "/"),
        "completed_at": utc_now(),
    }
    attempt_payload["attempt_hash"] = canonical_hash(attempt_payload)
    atomic_write_json(fix_dir / "result.json", attempt_payload)
    status_record["status"] = "fixed"
    status_record["history"].append(attempt_payload)
    state["active_finding"] = None
    state["expected_workspace_guard_hash"] = current["guard_hash"]
    state["events"].append(
        {
            "at": utc_now(),
            "event": "finding_fixed",
            "finding_id": args.finding,
            "attempt": active["attempt"],
            "changed_paths": sorted(changed_paths),
            "attempt_hash": attempt_payload["attempt_hash"],
        }
    )
    save_state(run_dir, state)
    print(f"[OK] Retained fix for {args.finding}")
    print(f"Changed paths: {', '.join(sorted(changed_paths)) if changed_paths else 'none (explicitly allowed)'}")
    print(f"Attempt artifact: {fix_dir / 'result.json'}")
    return 0


def command_rollback_finding(args: argparse.Namespace) -> int:
    repo = resolve_repo_root(args.repo_root)
    _, run_dir = resolve_run_dir(args, repo)
    state = load_state(run_dir)
    if state["phase"] != PHASE_FIXING or not state.get("active_finding"):
        raise ReviewError("rollback-finding requires an active finding in FIXING phase")
    active = state["active_finding"]
    if active["finding_id"] != args.finding:
        raise ReviewError(f"Active finding is {active['finding_id']}, not {args.finding}")
    reason = require_string(args.reason, "--reason")
    checkpoint_dir = run_dir / active["checkpoint"]
    expected_post = manual_recovery_observation(
        repo,
        checkpoint_dir,
        allowed_paths=active["allowed_paths"],
        context="The active finding attempt",
    )
    restored_authority = restore_checkpoint(
        repo, checkpoint_dir, expected_post=expected_post
    )
    restored_guard = restored_authority["identity"]["workspace_guard"]
    status_record = state["finding_status"][args.finding]
    outcome = {
        "attempt": active["attempt"],
        "outcome": "rolled_back",
        "reason": reason,
        "tests": active["test_results"],
        "at": utc_now(),
    }
    status_record["history"].append(outcome)
    if status_record["attempts"] >= status_record["max_attempts"]:
        status_record["status"] = "blocked"
        state["phase"] = PHASE_BLOCKED
    else:
        status_record["status"] = "repair_pending" if state["repair_round"] > 0 else "pending"
    state["active_finding"] = None
    state["expected_workspace_guard_hash"] = restored_guard["guard_hash"]
    state["events"].append(
        {
            "at": utc_now(),
            "event": "finding_attempt_rolled_back",
            "finding_id": args.finding,
            "attempt": active["attempt"],
            "reason": reason,
            "next_status": status_record["status"],
        }
    )
    save_state(run_dir, state)
    print(f"[OK] Restored checkpoint for {args.finding} attempt {active['attempt']}")
    print(f"Next status: {status_record['status']}")
    return 0


def command_abort_fixes(args: argparse.Namespace) -> int:
    repo = resolve_repo_root(args.repo_root)
    _, run_dir = resolve_run_dir(args, repo)
    state = load_state(run_dir)
    if state["phase"] not in MUTATION_PHASES:
        raise ReviewError(f"No active repair layer to abort in phase {state['phase']}")
    reason = require_string(args.reason, "--reason")
    pre_fix = state.get("pre_fix_checkpoint")
    if not pre_fix:
        raise ReviewError("Pre-fix checkpoint is missing")
    plan = load_verified_plan(run_dir, state)
    allowed_paths = {
        path for item in plan["items"] for path in item["allowed_paths"]
    }
    checkpoint_dir = run_dir / pre_fix
    expected_post = manual_recovery_observation(
        repo,
        checkpoint_dir,
        allowed_paths=allowed_paths,
        context="The repair layer",
    )
    restored_authority = restore_checkpoint(
        repo, checkpoint_dir, expected_post=expected_post
    )
    restored = restored_authority["identity"]["workspace_guard"]
    state["phase"] = PHASE_ABORTED
    state["active_finding"] = None
    state["expected_workspace_guard_hash"] = restored["guard_hash"]
    state["events"].append({"at": utc_now(), "event": "fix_layer_aborted", "reason": reason})
    atomic_write_text(
        run_dir / "abort.md",
        f"# Repair layer aborted\n\n- Reason: {reason}\n- Restored at: {utc_now()}\n- Workspace guard: `{restored['guard_hash']}`\n",
    )
    save_state(run_dir, state)
    print("[OK] Restored the complete pre-fix checkpoint")
    print(f"State: {PHASE_ABORTED}")
    return 0


def path_subset_hash(repo: Path, paths: Iterable[str]) -> str:
    payload = {path: path_state(repo_path(repo, path)) for path in sorted(set(paths))}
    return canonical_hash(payload)


def all_findings_fixed(state: dict[str, Any]) -> bool:
    return bool(state["approved_findings"]) and all(
        state["finding_status"].get(finding_id, {}).get("status") == "fixed"
        for finding_id in state["approved_findings"]
    )


def overall_repair_boundary(repo: Path, run_dir: Path, state: dict[str, Any], plan: dict[str, Any]) -> tuple[dict[str, Any], set[str], set[str]]:
    current = ensure_expected_workspace(repo, state)
    pre_fix_dir = run_dir / state["pre_fix_checkpoint"]
    pre_fix, _, _ = verify_checkpoint_integrity(repo, pre_fix_dir)
    before = pre_fix["workspace_guard"]
    before_identity = before["identity"]
    current_identity = current["identity"]
    if current_identity["head_sha"] != before_identity["head_sha"]:
        raise ReviewError("HEAD changed after begin-fix")
    if current_identity["branch"] != before_identity["branch"]:
        raise ReviewError("Branch changed after begin-fix")
    if current_identity["staged_patch_sha256"] != before_identity["staged_patch_sha256"]:
        raise ReviewError("Git index changed after begin-fix")
    changed_paths = diff_guard_paths(before, current)
    allowed = {path for item in plan["items"] for path in item["allowed_paths"]}
    outside = changed_paths - allowed
    return current, changed_paths, outside


def command_run_global_test(args: argparse.Namespace) -> int:
    repo = resolve_repo_root(args.repo_root)
    _, run_dir = resolve_run_dir(args, repo)
    state = load_state(run_dir)
    if state["phase"] != PHASE_FIXING or state.get("active_finding") is not None:
        raise ReviewError("run-global-test requires FIXING phase with no active finding")
    if not all_findings_fixed(state):
        raise ReviewError("Run global tests only after every approved finding is fixed")
    plan = load_verified_plan(run_dir, state)
    test = test_by_id(plan["global_tests"], args.test, "global")
    current, _, outside = overall_repair_boundary(repo, run_dir, state, plan)
    if outside:
        raise ReviewError("Repair layer already contains unapproved paths: " + ", ".join(sorted(outside)))
    prior_runs = state["global_test_results"].get(args.test, [])
    run_number = len(prior_runs) + 1
    checkpoint_dir = run_dir / "checkpoints" / "global-tests" / args.test / f"run-{run_number}"
    checkpoint = create_checkpoint(repo, checkpoint_dir, {path for item in plan["items"] for path in item["allowed_paths"]})
    result = execute_test_command(
        repo=repo,
        run_dir=run_dir,
        command=test["command"],
        working_directory=test["working_directory"],
        timeout_seconds=test["timeout_seconds"],
        log_relative=Path("tests") / "global" / args.test / f"run-{run_number}.log",
    )
    after_authority = repository_authority(repo)
    after = after_authority["identity"]["workspace_guard"]
    before_authority = checkpoint["repository_authority"]
    before_guard = before_authority["identity"]["workspace_guard"]
    changed_by_test = diff_guard_paths(before_guard, after)
    control_mutations_by_test = repository_control_mutations(
        before_authority, after_authority
    )
    result["workspace_guard_hash"] = after["guard_hash"]
    result["changed_paths_by_test"] = sorted(changed_by_test)
    result["control_mutations_by_test"] = control_mutations_by_test
    if changed_by_test or control_mutations_by_test:
        restored_authority = restore_checkpoint(
            repo,
            checkpoint_dir,
            expected_post=after_authority,
        )
        result["restored_after_mutation"] = True
        result["workspace_guard_hash"] = restored_authority["identity"]["workspace_guard"]["guard_hash"]
    else:
        result["restored_after_mutation"] = False
    state["global_test_results"].setdefault(args.test, []).append(result)
    state["events"].append(
        {
            "at": utc_now(),
            "event": "global_test_run",
            "test_id": args.test,
            "exit_code": result["exit_code"],
            "timed_out": result["timed_out"],
            "changed_paths_by_test": result["changed_paths_by_test"],
            "control_mutations_by_test": result["control_mutations_by_test"],
        }
    )
    save_state(run_dir, state)
    print(
        f"[{'OK' if result['exit_code'] == 0 and not result['timed_out'] and not changed_by_test and not control_mutations_by_test else 'FAIL'}] "
        f"Global test {args.test}"
    )
    print(f"Exit code: {result['exit_code'] if result['exit_code'] is not None else 'timeout'}")
    print(f"Log: {run_dir / result['log_path']}")
    if changed_by_test:
        raise ReviewError("Global test mutated tracked/untracked workspace paths and was restored: " + ", ".join(sorted(changed_by_test)))
    if control_mutations_by_test:
        raise ReviewError(
            "Global test mutated repository control state and was restored: "
            + ", ".join(control_mutations_by_test)
        )
    if result["timed_out"] or result["exit_code"] != 0:
        return 1
    return 0


def latest_fixed_attempt(state: dict[str, Any], finding_id: str) -> dict[str, Any]:
    history = state["finding_status"][finding_id]["history"]
    for entry in reversed(history):
        if entry.get("outcome") == "fixed":
            return entry
    raise ReviewError(f"No retained fixed attempt exists for {finding_id}")


def finding_test_refresh_runs(
    state: dict[str, Any], finding_id: str, test_id: str
) -> list[dict[str, Any]]:
    refresh_results = state.get("finding_test_refresh_results", {})
    if not isinstance(refresh_results, dict):
        raise ReviewError("finding_test_refresh_results must be an object")
    finding_results = refresh_results.get(finding_id, {})
    if not isinstance(finding_results, dict):
        raise ReviewError(
            f"finding_test_refresh_results.{finding_id} must be an object"
        )
    runs = finding_results.get(test_id, [])
    if not isinstance(runs, list) or any(not isinstance(run, dict) for run in runs):
        raise ReviewError(
            f"finding_test_refresh_results.{finding_id}.{test_id} must be an array of objects"
        )
    return runs


def command_refresh_finding_test(args: argparse.Namespace) -> int:
    repo = resolve_repo_root(args.repo_root)
    _, run_dir = resolve_run_dir(args, repo)
    state = load_state(run_dir)
    if state["phase"] != PHASE_FIXING or state.get("active_finding") is not None:
        raise ReviewError(
            "refresh-finding-test requires FIXING phase with no active finding"
        )
    if not all_findings_fixed(state):
        raise ReviewError(
            "refresh-finding-test is available only after every approved finding is fixed"
        )
    if args.finding not in state["approved_findings"]:
        raise ReviewError(f"Finding {args.finding} was not approved at Gate A")
    status = state["finding_status"].get(args.finding)
    if not status or status.get("status") != "fixed":
        raise ReviewError(f"Finding {args.finding} is not fixed")

    plan = load_verified_plan(run_dir, state)
    plan_gate = load_verified_plan_gate(run_dir, state)
    if not plan_gate["approved"] or plan_gate["plan_hash"] != plan["plan_hash"]:
        raise ReviewError("Gate B receipt does not authorize the current plan")
    item = plan_item_by_id(plan, args.finding)
    test = test_by_id(item["tests"], args.test, args.finding)
    current, _, outside = overall_repair_boundary(repo, run_dir, state, plan)
    if outside:
        raise ReviewError(
            "Aggregate repair delta contains unapproved paths: "
            + ", ".join(sorted(outside))
        )

    fixed_attempt = latest_fixed_attempt(state, args.finding)
    prior_runs = finding_test_refresh_runs(state, args.finding, args.test)
    run_number = len(prior_runs) + 1
    checkpoint_dir = (
        run_dir
        / "checkpoints"
        / "final-finding-tests"
        / args.finding
        / args.test
        / f"run-{run_number}"
    )
    aggregate_allowed_paths = {
        path for plan_item in plan["items"] for path in plan_item["allowed_paths"]
    }
    checkpoint = create_checkpoint(repo, checkpoint_dir, aggregate_allowed_paths)
    result = execute_test_command(
        repo=repo,
        run_dir=run_dir,
        command=test["command"],
        working_directory=test["working_directory"],
        timeout_seconds=test["timeout_seconds"],
        log_relative=(
            Path("tests")
            / "final-finding-tests"
            / args.finding
            / args.test
            / f"run-{run_number}.log"
        ),
    )

    after_authority = repository_authority(repo)
    after_test = after_authority["identity"]["workspace_guard"]
    before_authority = checkpoint["repository_authority"]
    before_test = before_authority["identity"]["workspace_guard"]
    changed_by_test = diff_guard_paths(before_test, after_test)
    control_mutations = repository_control_mutations(
        before_authority, after_authority
    )

    result["changed_paths_by_test"] = sorted(changed_by_test)
    result["control_mutations_by_test"] = list(dict.fromkeys(control_mutations))
    result["restored_after_mutation"] = False
    result["recovery_attempted"] = False
    result["recovery_completed"] = False
    result["recovery_error"] = None
    result["human_recovery_required"] = False
    if changed_by_test or control_mutations:
        result["recovery_attempted"] = True
        try:
            restore_checkpoint(
                repo,
                checkpoint_dir,
                expected_post=after_authority,
            )
            result["restored_after_mutation"] = True
            result["recovery_completed"] = True
        except ReviewError as exc:
            result["recovery_error"] = str(exc)
            result["human_recovery_required"] = True

    final_outside: set[str] = set()
    if result["human_recovery_required"]:
        final_guard = workspace_guard(repo)
    else:
        try:
            final_guard, _, final_outside = overall_repair_boundary(
                repo, run_dir, state, plan
            )
        except ReviewError as exc:
            final_guard = workspace_guard(repo)
            result["recovery_error"] = str(exc)
            result["human_recovery_required"] = True
    result["workspace_guard_hash"] = final_guard["guard_hash"]
    result["allowed_paths_hash"] = path_subset_hash(repo, item["allowed_paths"])
    result["boundary_violations"] = sorted(final_outside)
    result["fixed_attempt_hash"] = fixed_attempt["attempt_hash"]

    refresh_results = state.setdefault("finding_test_refresh_results", {})
    refresh_results.setdefault(args.finding, {}).setdefault(args.test, []).append(result)
    state["events"].append(
        {
            "at": utc_now(),
            "event": "fixed_finding_test_refreshed",
            "finding_id": args.finding,
            "test_id": args.test,
            "fixed_attempt_hash": fixed_attempt["attempt_hash"],
            "exit_code": result["exit_code"],
            "timed_out": result["timed_out"],
            "changed_paths_by_test": result["changed_paths_by_test"],
            "control_mutations_by_test": result["control_mutations_by_test"],
        }
    )
    save_state(run_dir, state)

    passed = (
        result["exit_code"] == 0
        and not result["timed_out"]
        and not changed_by_test
        and not control_mutations
        and not final_outside
        and not result["human_recovery_required"]
    )
    print(f"[{'OK' if passed else 'FAIL'}] Refreshed {args.finding} test {args.test}")
    print(
        f"Exit code: {result['exit_code'] if result['exit_code'] is not None else 'timeout'}"
    )
    print(f"Log: {run_dir / result['log_path']}")
    if changed_by_test or control_mutations:
        details = []
        if changed_by_test:
            details.append("paths: " + ", ".join(sorted(changed_by_test)))
        if control_mutations:
            details.append("controls: " + ", ".join(control_mutations))
        if result["human_recovery_required"]:
            raise ReviewError(
                "Approved test mutated repository state and automatic recovery was incomplete; "
                "human recovery is required ("
                + "; ".join(details)
                + f"). Cause: {result['recovery_error']}"
            )
        raise ReviewError(
            "Approved test mutated the workspace and was restored ("
            + "; ".join(details)
            + ")"
        )
    if result["timed_out"] or result["exit_code"] != 0:
        return 1
    return 0


def latest_finding_test_evidence(
    state: dict[str, Any],
    *,
    finding_id: str,
    test_id: str,
    fixed_attempt: dict[str, Any],
) -> dict[str, Any] | None:
    refresh_runs = finding_test_refresh_runs(state, finding_id, test_id)
    attempt_hash = require_sha256(
        fixed_attempt.get("attempt_hash"),
        f"finding_status.{finding_id}.fixed_attempt.attempt_hash",
    )
    matching_refresh_runs = [
        run for run in refresh_runs if run.get("fixed_attempt_hash") == attempt_hash
    ]
    if matching_refresh_runs:
        return matching_refresh_runs[-1]
    tests = require_object(
        fixed_attempt.get("tests"), f"finding_status.{finding_id}.fixed_attempt.tests"
    )
    attempt_runs = tests.get(test_id, [])
    if not isinstance(attempt_runs, list) or any(
        not isinstance(run, dict) for run in attempt_runs
    ):
        raise ReviewError(
            f"finding_status.{finding_id}.fixed_attempt.tests.{test_id} must be an array of objects"
        )
    return attempt_runs[-1] if attempt_runs else None


def command_prepare_verification(args: argparse.Namespace) -> int:
    repo = resolve_repo_root(args.repo_root)
    _, run_dir = resolve_run_dir(args, repo)
    state = load_state(run_dir)
    if state["phase"] != PHASE_FIXING or state.get("active_finding") is not None:
        raise ReviewError("prepare-verification requires FIXING phase with no active finding")
    if not all_findings_fixed(state):
        unresolved = [
            f"{finding_id}:{state['finding_status'].get(finding_id, {}).get('status', 'missing')}"
            for finding_id in state["approved_findings"]
            if state["finding_status"].get(finding_id, {}).get("status") != "fixed"
        ]
        raise ReviewError("Not all approved findings are fixed: " + ", ".join(unresolved))
    plan = load_verified_plan(run_dir, state)
    current, changed_paths, outside = overall_repair_boundary(repo, run_dir, state, plan)
    if outside:
        raise ReviewError("Aggregate repair delta contains unapproved paths: " + ", ".join(sorted(outside)))

    stale_finding_tests: list[str] = []
    for item in plan["items"]:
        attempt = latest_fixed_attempt(state, item["finding_id"])
        current_subset = path_subset_hash(repo, item["allowed_paths"])
        for test in item["tests"]:
            if not test["required"]:
                continue
            latest = latest_finding_test_evidence(
                state,
                finding_id=item["finding_id"],
                test_id=test["id"],
                fixed_attempt=attempt,
            )
            if latest is None:
                stale_finding_tests.append(f"{item['finding_id']}:{test['id']} not run")
                continue
            if latest["timed_out"] or latest["exit_code"] != 0:
                stale_finding_tests.append(f"{item['finding_id']}:{test['id']} failed")
            elif latest.get("allowed_paths_hash") != current_subset:
                stale_finding_tests.append(f"{item['finding_id']}:{test['id']} stale for approved paths")
            elif latest.get("changed_paths_by_test"):
                stale_finding_tests.append(f"{item['finding_id']}:{test['id']} mutated workspace")
            elif latest.get("control_mutations_by_test"):
                stale_finding_tests.append(
                    f"{item['finding_id']}:{test['id']} mutated repository controls"
                )
            elif latest.get("boundary_violations"):
                stale_finding_tests.append(f"{item['finding_id']}:{test['id']} boundary violation")
    if stale_finding_tests:
        raise ReviewError(
            "Finding tests are stale or failing at final repair state; reopen/rerun as appropriate: "
            + ", ".join(stale_finding_tests)
        )

    stale_global: list[str] = []
    for test in plan["global_tests"]:
        if not test["required"]:
            continue
        runs = state["global_test_results"].get(test["id"], [])
        if not runs:
            stale_global.append(f"{test['id']} not run")
            continue
        latest = runs[-1]
        if latest["timed_out"] or latest["exit_code"] != 0:
            stale_global.append(f"{test['id']} failed")
        elif latest["workspace_guard_hash"] != current["guard_hash"]:
            stale_global.append(f"{test['id']} stale after later edits")
        elif latest.get("changed_paths_by_test"):
            stale_global.append(f"{test['id']} mutated workspace")
    if stale_global:
        raise ReviewError("Required global tests are stale or failing: " + ", ".join(stale_global))

    pre_fix_dir = run_dir / state["pre_fix_checkpoint"]
    fix_patch = render_checkpoint_diff(pre_fix_dir, repo, changed_paths)
    atomic_write_text(run_dir / "fix-summary.patch", fix_patch)
    finding_results = {
        finding_id: {
            "status": state["finding_status"][finding_id]["status"],
            "attempts": state["finding_status"][finding_id]["attempts"],
            "history": state["finding_status"][finding_id]["history"],
        }
        for finding_id in state["approved_findings"]
    }
    summary = {
        "schema_version": FIX_SUMMARY_SCHEMA,
        "scope_hash": state["scope_hash"],
        "plan_hash": plan["plan_hash"],
        "approved_findings": state["approved_findings"],
        "changed_paths": sorted(changed_paths),
        "finding_results": finding_results,
        "finding_test_refresh_results": state.get(
            "finding_test_refresh_results", {}
        ),
        "global_test_results": state["global_test_results"],
        "repair_round": state["repair_round"],
        "prepared_at": utc_now(),
        "fix_patch_sha256": sha256_file(run_dir / "fix-summary.patch"),
    }
    fix_summary_hash = canonical_hash(summary)
    summary["fix_summary_hash"] = fix_summary_hash
    atomic_write_json(run_dir / "fix-summary.json", summary)
    state["phase"] = PHASE_VERIFYING
    state["hashes"]["fix_summary_hash"] = fix_summary_hash
    state["events"].append(
        {
            "at": utc_now(),
            "event": "verification_prepared",
            "fix_summary_hash": fix_summary_hash,
            "changed_paths": sorted(changed_paths),
            "repair_round": state["repair_round"],
        }
    )
    save_state(run_dir, state)
    print(f"[OK] Post-fix verification bundle prepared: {fix_summary_hash}")
    print(f"Changed paths: {', '.join(sorted(changed_paths))}")
    print(f"Bundle: {run_dir / 'fix-summary.json'}")
    return 0


def verify_current_quote(repo: Path, file: str, line_start: int, quote: str) -> None:
    target = repo_path(repo, file)
    if not target.exists() or not target.is_file():
        raise ReviewError(f"Verification evidence file is missing: {file}")
    text = target.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    if line_start > len(lines):
        raise ReviewError(f"Verification evidence line exceeds file length: {file}:{line_start}")
    window = "\n".join(lines[max(0, line_start - 2) : min(len(lines), line_start + 4)])
    if quote not in window and quote not in text:
        raise ReviewError(f"Verification evidence quote was not found in current file {file}")


def validate_verification(raw: Any, *, repo: Path, state: dict[str, Any], plan: dict[str, Any], fix_summary: dict[str, Any]) -> dict[str, Any]:
    obj = require_object(raw, "post-fix verification")
    top_keys = {
        "schema_version",
        "scope_hash",
        "plan_hash",
        "fix_summary_hash",
        "verifier_id",
        "independence_group",
        "mode",
        "finding_results",
        "regressions",
        "record_only_observations",
        "verdict",
        "summary",
        "limitations",
    }
    require_exact_keys(obj, top_keys, "post-fix verification")
    if obj["schema_version"] != VERIFICATION_SCHEMA:
        raise ReviewError("Unsupported verification schema_version")
    if obj["scope_hash"] != state["scope_hash"]:
        raise ReviewError("Verification scope_hash does not match the run")
    if obj["plan_hash"] != plan["plan_hash"]:
        raise ReviewError("Verification plan_hash does not match the approved plan")
    if obj["fix_summary_hash"] != fix_summary["fix_summary_hash"]:
        raise ReviewError("Verification fix_summary_hash does not match the prepared fix bundle")
    mode = require_string(obj["mode"], "verification.mode")
    if mode not in VALIDATION_MODES:
        raise ReviewError(f"verification.mode must be one of {sorted(VALIDATION_MODES)}")

    finding_keys = {
        "finding_id",
        "status",
        "root_cause_resolved",
        "reason",
        "evidence_checked",
        "tests_checked",
    }
    finding_results: list[dict[str, Any]] = []
    seen_findings: set[str] = set()
    for index, raw_result in enumerate(require_array(obj["finding_results"], "verification.finding_results")):
        context = f"verification.finding_results[{index}]"
        result = require_object(raw_result, context)
        require_exact_keys(result, finding_keys, context)
        finding_id = require_string(result["finding_id"], f"{context}.finding_id")
        if finding_id in seen_findings:
            raise ReviewError(f"Duplicate verification result for {finding_id}")
        seen_findings.add(finding_id)
        status_value = require_string(result["status"], f"{context}.status")
        if status_value not in {"resolved", "unresolved", "uncertain"}:
            raise ReviewError(f"{context}.status is invalid")
        root_resolved = require_bool(result["root_cause_resolved"], f"{context}.root_cause_resolved")
        if status_value == "resolved" and not root_resolved:
            raise ReviewError(f"{context}: resolved requires root_cause_resolved=true")
        if status_value != "resolved" and root_resolved:
            raise ReviewError(f"{context}: unresolved/uncertain requires root_cause_resolved=false")
        finding_results.append(
            {
                "finding_id": finding_id,
                "status": status_value,
                "root_cause_resolved": root_resolved,
                "reason": require_string(result["reason"], f"{context}.reason"),
                "evidence_checked": require_string_array(result["evidence_checked"], f"{context}.evidence_checked"),
                "tests_checked": require_string_array(result["tests_checked"], f"{context}.tests_checked"),
            }
        )
    approved = set(state["approved_findings"])
    if seen_findings != approved:
        missing = sorted(approved - seen_findings)
        extra = sorted(seen_findings - approved)
        raise ReviewError(
            "Verification must cover every approved finding exactly once"
            + (f"; missing {', '.join(missing)}" if missing else "")
            + (f"; unknown {', '.join(extra)}" if extra else "")
        )

    regression_keys = {
        "regression_id",
        "title",
        "severity",
        "file",
        "line_start",
        "evidence_quote",
        "caused_by_fix",
        "repair_owner_finding_id",
        "repair_paths",
        "reason",
    }
    regressions: list[dict[str, Any]] = []
    regression_ids: set[str] = set()
    for index, raw_regression in enumerate(require_array(obj["regressions"], "verification.regressions")):
        context = f"verification.regressions[{index}]"
        regression = require_object(raw_regression, context)
        require_exact_keys(regression, regression_keys, context)
        regression_id = require_string(regression["regression_id"], f"{context}.regression_id")
        if regression_id in regression_ids or not re.fullmatch(r"R[0-9]{3,}", regression_id):
            raise ReviewError(f"{context}.regression_id must be unique and match R###")
        regression_ids.add(regression_id)
        severity = require_string(regression["severity"], f"{context}.severity")
        if severity not in SEVERITIES:
            raise ReviewError(f"{context}.severity is invalid")
        if require_bool(regression["caused_by_fix"], f"{context}.caused_by_fix") is not True:
            raise ReviewError(f"{context}: only fix-caused regressions belong in regressions")
        owner = require_string(regression["repair_owner_finding_id"], f"{context}.repair_owner_finding_id")
        if owner not in approved:
            raise ReviewError(f"{context}: repair owner {owner} is not an approved finding")
        file = normalize_repo_path(require_string(regression["file"], f"{context}.file"))
        line_start = require_int(regression["line_start"], f"{context}.line_start", minimum=1)
        quote = require_string(regression["evidence_quote"], f"{context}.evidence_quote")
        verify_current_quote(repo, file, line_start, quote)
        repair_paths = [normalize_repo_path(path) for path in require_string_array(regression["repair_paths"], f"{context}.repair_paths")]
        if not repair_paths:
            raise ReviewError(f"{context}.repair_paths must not be empty")
        regressions.append(
            {
                "regression_id": regression_id,
                "title": require_string(regression["title"], f"{context}.title"),
                "severity": severity,
                "file": file,
                "line_start": line_start,
                "evidence_quote": quote,
                "caused_by_fix": True,
                "repair_owner_finding_id": owner,
                "repair_paths": repair_paths,
                "reason": require_string(regression["reason"], f"{context}.reason"),
            }
        )

    observation_keys = {"title", "file", "line_start", "reason"}
    observations: list[dict[str, Any]] = []
    for index, raw_observation in enumerate(
        require_array(obj["record_only_observations"], "verification.record_only_observations")
    ):
        context = f"verification.record_only_observations[{index}]"
        observation = require_object(raw_observation, context)
        require_exact_keys(observation, observation_keys, context)
        observations.append(
            {
                "title": require_string(observation["title"], f"{context}.title"),
                "file": normalize_repo_path(require_string(observation["file"], f"{context}.file")),
                "line_start": require_int(observation["line_start"], f"{context}.line_start", minimum=1),
                "reason": require_string(observation["reason"], f"{context}.reason"),
            }
        )

    verdict = require_string(obj["verdict"], "verification.verdict")
    if verdict not in {"pass", "repair_required", "blocked"}:
        raise ReviewError("verification.verdict must be pass, repair_required, or blocked")
    unresolved = [result for result in finding_results if result["status"] == "unresolved"]
    uncertain = [result for result in finding_results if result["status"] == "uncertain"]
    if verdict == "pass" and (unresolved or uncertain or regressions):
        raise ReviewError("verification.verdict=pass requires all findings resolved and no regressions")
    if verdict == "repair_required" and not (unresolved or regressions):
        raise ReviewError("verification.verdict=repair_required requires an unresolved finding or fix-caused regression")
    if uncertain and verdict != "blocked":
        raise ReviewError("An uncertain post-fix result requires verdict=blocked")

    return {
        "schema_version": VERIFICATION_SCHEMA,
        "scope_hash": state["scope_hash"],
        "plan_hash": plan["plan_hash"],
        "fix_summary_hash": fix_summary["fix_summary_hash"],
        "verifier_id": require_string(obj["verifier_id"], "verification.verifier_id"),
        "independence_group": require_string(obj["independence_group"], "verification.independence_group"),
        "mode": mode,
        "finding_results": finding_results,
        "regressions": regressions,
        "record_only_observations": observations,
        "verdict": verdict,
        "summary": require_string(obj["summary"], "verification.summary"),
        "limitations": require_string_array(obj["limitations"], "verification.limitations"),
    }


def render_verification_markdown(verification: dict[str, Any], final_phase: str, verification_hash: str) -> str:
    lines = [
        "# Post-fix verification",
        "",
        f"- Recorded verdict: `{verification['verdict']}`",
        f"- Controller state: `{final_phase}`",
        f"- Verification hash: `{verification_hash}`",
        f"- Mode: `{verification['mode']}`",
        f"- Verifier: `{verification['verifier_id']}` / `{verification['independence_group']}`",
        "",
        "## Summary",
        "",
        verification["summary"],
        "",
        "## Approved finding results",
        "",
    ]
    for result in verification["finding_results"]:
        lines.extend(
            [
                f"### {result['finding_id']} — {result['status']}",
                "",
                f"- Root cause resolved: `{str(result['root_cause_resolved']).lower()}`",
                f"- Reason: {result['reason']}",
                f"- Evidence checked: {', '.join(result['evidence_checked']) if result['evidence_checked'] else 'none'}",
                f"- Tests checked: {', '.join(result['tests_checked']) if result['tests_checked'] else 'none'}",
                "",
            ]
        )
    lines.extend(["## Fix-caused regressions", ""])
    if not verification["regressions"]:
        lines.append("- none")
    for regression in verification["regressions"]:
        lines.append(
            f"- **{regression['regression_id']}** [{regression['severity']}] `{regression['file']}:{regression['line_start']}` "
            f"owned by `{regression['repair_owner_finding_id']}` — {regression['title']}: {regression['reason']}"
        )
    lines.extend(["", "## Record-only observations", ""])
    if not verification["record_only_observations"]:
        lines.append("- none")
    for observation in verification["record_only_observations"]:
        lines.append(
            f"- `{observation['file']}:{observation['line_start']}` — {observation['title']}: {observation['reason']}"
        )
    if verification["limitations"]:
        lines.extend(["", "## Limitations", ""])
        lines.extend(f"- {item}" for item in verification["limitations"])
    return "\n".join(lines) + "\n"


def command_record_verification(args: argparse.Namespace) -> int:
    repo = resolve_repo_root(args.repo_root)
    _, run_dir = resolve_run_dir(args, repo)
    state = load_state(run_dir)
    if state["phase"] != PHASE_VERIFYING:
        raise ReviewError(f"record-verification requires phase {PHASE_VERIFYING}; current phase is {state['phase']}")
    ensure_expected_workspace(repo, state)
    plan = load_verified_plan(run_dir, state)
    fix_summary = load_verified_fix_summary(run_dir, state)
    verification = validate_verification(
        load_json(Path(args.input).expanduser().resolve()),
        repo=repo,
        state=state,
        plan=plan,
        fix_summary=fix_summary,
    )
    payload_for_hash = copy.deepcopy(verification)
    verification_hash = canonical_hash(payload_for_hash)
    verification["verification_hash"] = verification_hash
    verification["recorded_at"] = utc_now()
    atomic_write_json(run_dir / "verification.json", verification)
    state["hashes"]["verification_hash"] = verification_hash

    repair_targets = {
        result["finding_id"]
        for result in verification["finding_results"]
        if result["status"] == "unresolved"
    }
    repair_targets.update(regression["repair_owner_finding_id"] for regression in verification["regressions"])
    out_of_plan: list[dict[str, Any]] = []
    exhausted: list[str] = []
    for regression in verification["regressions"]:
        item = plan_item_by_id(plan, regression["repair_owner_finding_id"])
        outside = sorted(set(regression["repair_paths"]) - set(item["allowed_paths"]))
        if outside:
            out_of_plan.append(
                {
                    "regression_id": regression["regression_id"],
                    "repair_owner_finding_id": regression["repair_owner_finding_id"],
                    "outside_paths": outside,
                }
            )
    for finding_id in sorted(repair_targets):
        status = state["finding_status"][finding_id]
        if status["attempts"] >= status["max_attempts"]:
            exhausted.append(finding_id)

    if verification["verdict"] == "pass":
        state["phase"] = PHASE_COMPLETE
        state["repair_targets"] = []
    elif verification["verdict"] == "blocked":
        state["phase"] = PHASE_BLOCKED
        state["repair_targets"] = []
    elif out_of_plan:
        state["phase"] = PHASE_PLAN_AMENDMENT
        state["repair_targets"] = sorted(repair_targets)
    elif exhausted or state["repair_round"] >= plan["max_repair_rounds"]:
        state["phase"] = PHASE_BLOCKED
        state["repair_targets"] = sorted(repair_targets)
    else:
        state["phase"] = PHASE_REPAIR_REQUIRED
        state["repair_targets"] = sorted(repair_targets)

    repair_evaluation = {
        "verification_hash": verification_hash,
        "requested_targets": sorted(repair_targets),
        "out_of_plan": out_of_plan,
        "attempts_exhausted": exhausted,
        "repair_round": state["repair_round"],
        "max_repair_rounds": plan["max_repair_rounds"],
        "next_phase": state["phase"],
        "evaluated_at": utc_now(),
    }
    atomic_write_json(run_dir / "repair-evaluation.json", repair_evaluation)
    atomic_write_text(run_dir / "verification.md", render_verification_markdown(verification, state["phase"], verification_hash))
    state["events"].append(
        {
            "at": utc_now(),
            "event": "verification_recorded",
            "verification_hash": verification_hash,
            "verdict": verification["verdict"],
            "next_phase": state["phase"],
            "repair_targets": sorted(repair_targets),
            "out_of_plan": out_of_plan,
            "attempts_exhausted": exhausted,
        }
    )
    save_state(run_dir, state)
    print(f"[OK] Verification recorded: {verification_hash}")
    print(f"Verifier verdict: {verification['verdict']}")
    print(f"Controller state: {state['phase']}")
    if out_of_plan:
        print("Plan amendment required for paths: " + ", ".join(sorted({path for item in out_of_plan for path in item['outside_paths']})))
    if exhausted:
        print("Attempt budget exhausted: " + ", ".join(exhausted))
    return 0


def command_begin_repair(args: argparse.Namespace) -> int:
    repo = resolve_repo_root(args.repo_root)
    _, run_dir = resolve_run_dir(args, repo)
    state = load_state(run_dir)
    if state["phase"] != PHASE_REPAIR_REQUIRED:
        raise ReviewError(f"begin-repair requires phase {PHASE_REPAIR_REQUIRED}; current phase is {state['phase']}")
    current = ensure_expected_workspace(repo, state)
    plan = load_verified_plan(run_dir, state)
    if state["repair_round"] >= plan["max_repair_rounds"]:
        state["phase"] = PHASE_BLOCKED
        save_state(run_dir, state)
        raise ReviewError("Post-fix repair-round budget is exhausted")
    targets = state.get("repair_targets", [])
    if not targets:
        raise ReviewError("No repair targets were recorded")
    next_round = state["repair_round"] + 1
    history_dir = run_dir / "verification-history" / f"round-{state['repair_round']}"
    artifact_mkdir(history_dir, parents=True, exist_ok=True)
    for name in ("fix-summary.json", "fix-summary.patch", "verification.json", "verification.md", "repair-evaluation.json"):
        source = run_dir / name
        if artifact_exists(source):
            atomic_write_bytes(history_dir / name, artifact_read_bytes(source))
    for finding_id in targets:
        status = state["finding_status"][finding_id]
        if status["attempts"] >= status["max_attempts"]:
            state["phase"] = PHASE_BLOCKED
            save_state(run_dir, state)
            raise ReviewError(f"Finding {finding_id} has no remaining approved attempts")
        status["status"] = "repair_pending"
    state["repair_round"] = next_round
    state["phase"] = PHASE_FIXING
    state["active_finding"] = None
    state["expected_workspace_guard_hash"] = current["guard_hash"]
    state["events"].append(
        {
            "at": utc_now(),
            "event": "repair_round_started",
            "repair_round": next_round,
            "targets": targets,
        }
    )
    save_state(run_dir, state)
    print(f"[OK] Began bounded repair round {next_round}")
    print("Targets: " + ", ".join(targets))
    return 0


def state_summary(state: dict[str, Any], run_dir: Path) -> dict[str, Any]:
    return {
        "run_id": state["run_id"],
        "phase": state["phase"],
        "repo_root": state["repo_root"],
        "artifact_directory": str(run_dir),
        "scope_hash": state["scope_hash"],
        "hashes": state["hashes"],
        "gates": state["gates"],
        "approved_findings": state["approved_findings"],
        "finding_status": {
            finding_id: {
                "status": record["status"],
                "attempts": record["attempts"],
                "max_attempts": record["max_attempts"],
            }
            for finding_id, record in state.get("finding_status", {}).items()
        },
        "active_finding": state.get("active_finding"),
        "repair_round": state.get("repair_round", 0),
        "repair_targets": state.get("repair_targets", []),
        "updated_at": state["updated_at"],
    }


def command_status(args: argparse.Namespace) -> int:
    repo = resolve_repo_root(args.repo_root)
    _, run_dir = resolve_run_dir(args, repo)
    state = load_state(run_dir)
    summary = state_summary(state, run_dir)
    if args.json:
        print(json.dumps(summary, indent=2, sort_keys=True, ensure_ascii=False))
        return 0
    print(f"Run ID: {summary['run_id']}")
    print(f"Phase: {summary['phase']}")
    print(f"Scope hash: {summary['scope_hash']}")
    print(f"Artifact directory: {summary['artifact_directory']}")
    print(f"Approved findings: {', '.join(summary['approved_findings']) if summary['approved_findings'] else 'none'}")
    if summary["finding_status"]:
        print("Finding status:")
        for finding_id, record in sorted(summary["finding_status"].items()):
            print(
                f"  - {finding_id}: {record['status']} "
                f"(attempts {record['attempts']}/{record['max_attempts']})"
            )
    if summary["repair_targets"]:
        print("Repair targets: " + ", ".join(summary["repair_targets"]))
    return 0


def add_common_run_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--repo-root", default=".", help="Path inside the Git repository (default: current directory).")
    parser.add_argument("--artifact-root", default="", help="Override the local artifact root. Default: git rev-parse --git-path material-code-review.")
    parser.add_argument("--run-id", default="", help="Run ID. May also be supplied through MATERIAL_REVIEW_RUN_ID.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Evidence and state controller for the material-code-review skill.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {TOOL_VERSION}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="Resolve, freeze, hash, and snapshot the review scope.")
    init_parser.add_argument("--repo-root", default=".")
    init_parser.add_argument("--artifact-root", default="")
    init_parser.add_argument("--run-id", default="")
    init_parser.add_argument("--scope", choices=["auto", "uncommitted", "branch", "range"], default="auto")
    init_parser.add_argument("--base", default="", help="Base ref for branch/range scope.")
    init_parser.add_argument("--head", default="", help="Head ref for range scope.")
    init_parser.add_argument("--exclude-untracked", action="store_true", help="Explicitly exclude untracked files from working-tree scope.")
    init_parser.add_argument("--max-snapshot-file-bytes", type=int, default=2 * 1024 * 1024)
    init_parser.add_argument("--max-snapshot-total-bytes", type=int, default=25 * 1024 * 1024)
    init_parser.set_defaults(func=command_init)

    check_parser = subparsers.add_parser("check-scope", help="Recompute and compare the frozen scope hash.")
    add_common_run_options(check_parser)
    check_parser.set_defaults(func=command_check_scope)

    coverage_parser = subparsers.add_parser("record-coverage", help="Validate and record the immutable review coverage plan.")
    add_common_run_options(coverage_parser)
    coverage_parser.add_argument("--input", required=True, help="Coverage-plan JSON path.")
    coverage_parser.set_defaults(func=command_record_coverage)

    ingest_parser = subparsers.add_parser("ingest-candidates", help="Validate and normalize candidate reviewer JSON outputs.")
    add_common_run_options(ingest_parser)
    ingest_parser.add_argument("--input", action="append", required=True, help="Candidate-set JSON path. Repeat for each reviewer.")
    ingest_parser.set_defaults(func=command_ingest_candidates)

    ledger_parser = subparsers.add_parser("compile-ledger", help="Validate adjudication and create the kept/discarded ledger.")
    add_common_run_options(ledger_parser)
    ledger_parser.add_argument("--input", required=True, help="Adjudication JSON path.")
    ledger_parser.set_defaults(func=command_compile_ledger)

    findings_gate_parser = subparsers.add_parser("gate-findings", help="Record the mandatory Gate A user decisions.")
    add_common_run_options(findings_gate_parser)
    findings_gate_parser.add_argument("--approve", action="append", default=[], help="Comma-separated kept finding IDs to approve.")
    findings_gate_parser.add_argument("--reject", action="append", default=[], help="Comma-separated kept finding IDs to reject.")
    findings_gate_parser.add_argument("--defer", action="append", default=[], help="Comma-separated kept finding IDs to defer.")
    findings_gate_parser.add_argument("--accept-empty", action="store_true", help="Accept a ledger with no kept findings.")
    findings_gate_parser.add_argument("--user-statement", required=True, help="Exact or faithful user decision statement.")
    findings_gate_parser.set_defaults(func=command_gate_findings)

    plan_parser = subparsers.add_parser("validate-plan", help="Validate an exact repair plan for Gate-A-approved findings.")
    add_common_run_options(plan_parser)
    plan_parser.add_argument("--input", required=True, help="Fix-plan JSON path.")
    plan_parser.set_defaults(func=command_validate_plan)

    plan_gate_parser = subparsers.add_parser("gate-plan", help="Record the mandatory Gate B decision for the exact plan hash.")
    add_common_run_options(plan_gate_parser)
    decision_group = plan_gate_parser.add_mutually_exclusive_group(required=True)
    decision_group.add_argument("--approve", action="store_true")
    decision_group.add_argument("--reject", action="store_true")
    plan_gate_parser.add_argument("--user-statement", required=True)
    plan_gate_parser.set_defaults(func=command_gate_plan)

    begin_fix_parser = subparsers.add_parser("begin-fix", help="Capture the pre-fix checkpoint after Gate B.")
    add_common_run_options(begin_fix_parser)
    begin_fix_parser.set_defaults(func=command_begin_fix)

    start_parser = subparsers.add_parser("start-finding", help="Start a checkpointed attempt for one approved finding.")
    add_common_run_options(start_parser)
    start_parser.add_argument("--finding", required=True)
    start_parser.set_defaults(func=command_start_finding)

    run_test_parser = subparsers.add_parser("run-test", help="Run one Gate-B-approved finding test and log it.")
    add_common_run_options(run_test_parser)
    run_test_parser.add_argument("--finding", required=True)
    run_test_parser.add_argument("--test", required=True)
    run_test_parser.set_defaults(func=command_run_test)

    finish_parser = subparsers.add_parser("finish-finding", help="Retain a verified attempt or mark a restored finding blocked.")
    add_common_run_options(finish_parser)
    finish_parser.add_argument("--finding", required=True)
    finish_parser.add_argument("--status", choices=["fixed", "blocked"], required=True)
    finish_parser.add_argument("--note", required=True)
    finish_parser.add_argument("--manual-evidence", action="append", default=[])
    finish_parser.add_argument("--allow-no-change", action="store_true")
    finish_parser.set_defaults(func=command_finish_finding)

    rollback_parser = subparsers.add_parser("rollback-finding", help="Restore the active finding checkpoint.")
    add_common_run_options(rollback_parser)
    rollback_parser.add_argument("--finding", required=True)
    rollback_parser.add_argument("--reason", required=True)
    rollback_parser.set_defaults(func=command_rollback_finding)

    global_test_parser = subparsers.add_parser("run-global-test", help="Run a Gate-B-approved global validation command.")
    add_common_run_options(global_test_parser)
    global_test_parser.add_argument("--test", required=True)
    global_test_parser.set_defaults(func=command_run_global_test)

    refresh_test_parser = subparsers.add_parser(
        "refresh-finding-test",
        help="Rerun one Gate-B-approved test for a fixed finding at the final repair state.",
    )
    add_common_run_options(refresh_test_parser)
    refresh_test_parser.add_argument("--finding", required=True)
    refresh_test_parser.add_argument("--test", required=True)
    refresh_test_parser.set_defaults(func=command_refresh_finding_test)

    prepare_parser = subparsers.add_parser("prepare-verification", help="Create the bounded fix-only verification bundle.")
    add_common_run_options(prepare_parser)
    prepare_parser.set_defaults(func=command_prepare_verification)

    record_parser = subparsers.add_parser("record-verification", help="Validate and record bounded post-fix verification.")
    add_common_run_options(record_parser)
    record_parser.add_argument("--input", required=True, help="Verification JSON path.")
    record_parser.set_defaults(func=command_record_verification)

    repair_parser = subparsers.add_parser("begin-repair", help="Begin one bounded in-plan post-fix repair round.")
    add_common_run_options(repair_parser)
    repair_parser.set_defaults(func=command_begin_repair)

    abort_parser = subparsers.add_parser("abort-fixes", help="Restore the complete pre-fix checkpoint and stop.")
    add_common_run_options(abort_parser)
    abort_parser.add_argument("--reason", required=True)
    abort_parser.set_defaults(func=command_abort_fixes)

    status_parser = subparsers.add_parser("status", help="Show the active run state.")
    add_common_run_options(status_parser)
    status_parser.add_argument("--json", action="store_true")
    status_parser.set_defaults(func=command_status)

    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    workflow_profile: str = WORKFLOW_PROFILE_REVIEW,
) -> int:
    if workflow_profile not in {WORKFLOW_PROFILE_REVIEW, SIMPLIFICATION_PROFILE}:
        raise ValueError(f"Unsupported internal workflow profile: {workflow_profile}")
    parser = build_parser()
    args = parser.parse_args(argv)
    args._workflow_profile = workflow_profile
    if hasattr(args, "base") and args.base == "":
        args.base = None
    if hasattr(args, "head") and args.head == "":
        args.head = None
    if hasattr(args, "artifact_root") and args.artifact_root == "":
        args.artifact_root = None
    if hasattr(args, "run_id") and args.run_id == "":
        args.run_id = None
    try:
        enforce_command_compatibility(args)
        return int(args.func(args))
    except ReviewError as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("[FAIL] Interrupted", file=sys.stderr)
        return 130
    finally:
        _close_active_artifact_authority()


if __name__ == "__main__":
    raise SystemExit(main())
