#!/usr/bin/env python3
"""Transactional publication for package archives and checksum sidecars."""

from __future__ import annotations

import os
import errno
import hashlib
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


RECOVERY_SCHEMA_VERSION = "package-publication/recovery/v1"
PUBLICATION_LOCK_TIMEOUT_SECONDS = 10.0
PUBLICATION_LOCK_POLL_SECONDS = 0.05


class PublicationRecoveryError(OSError):
    """Report a publication failure whose prior state was not fully restored."""

    def __init__(self, recovery_record: dict[str, Any]) -> None:
        self.recovery_record = recovery_record
        remaining = len(recovery_record["unrestored_backups"])
        super().__init__(
            "package publication failed and recovery was incomplete; "
            f"{remaining} prior output backup(s) retained"
        )


class PublicationLockTimeoutError(TimeoutError):
    """Report bounded cooperative publication-lock contention."""


def _normalized_destination_identity(destination: Path) -> str:
    resolved = destination.expanduser().resolve(strict=False)
    return os.path.normcase(os.fspath(resolved))


def _publication_lock_directory() -> Path:
    home_identity = os.path.normcase(
        os.path.abspath(os.path.expanduser("~"))
    ).encode("utf-8", "surrogatepass")
    user_digest = hashlib.sha256(home_identity).hexdigest()[:16]
    lock_directory = (
        Path(tempfile.gettempdir())
        / f"material-code-review-publication-locks-{user_digest}"
    )
    lock_directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    return lock_directory


def _publication_lock_path(destination_identity: str) -> Path:
    digest = hashlib.sha256(
        destination_identity.encode("utf-8", "surrogatepass")
    ).hexdigest()
    return _publication_lock_directory() / f"{digest}.lock"


def _acquire_descriptor_lock(descriptor: int) -> None:
    if os.name == "posix":
        import fcntl

        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return
    if os.name == "nt":
        import msvcrt

        os.lseek(descriptor, 0, os.SEEK_SET)
        msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
        return
    raise OSError(f"publication locking is unsupported on platform {os.name!r}")


def _release_descriptor_lock(descriptor: int) -> None:
    if os.name == "posix":
        import fcntl

        fcntl.flock(descriptor, fcntl.LOCK_UN)
        return
    if os.name == "nt":
        import msvcrt

        os.lseek(descriptor, 0, os.SEEK_SET)
        msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
        return
    raise OSError(f"publication locking is unsupported on platform {os.name!r}")


def _lock_is_contended(error: OSError) -> bool:
    return error.errno in {errno.EACCES, errno.EAGAIN}


def _release_publication_locks(
    locked_descriptors: list[tuple[Path, int]],
) -> list[dict[str, str]]:
    failures: list[dict[str, str]] = []
    for lock_path, descriptor in reversed(locked_descriptors):
        try:
            _release_descriptor_lock(descriptor)
        except BaseException as error:
            failures.append(
                {
                    "operation": "release_publication_lock",
                    "path": str(lock_path),
                    **_exception_record(error),
                }
            )
        try:
            os.close(descriptor)
        except BaseException as error:
            failures.append(
                {
                    "operation": "close_publication_lock",
                    "path": str(lock_path),
                    **_exception_record(error),
                }
            )
    return failures


@contextmanager
def _publication_locks(
    destinations: list[Path],
    *,
    timeout_seconds: float = PUBLICATION_LOCK_TIMEOUT_SECONDS,
) -> Iterator[None]:
    identities = sorted(
        {_normalized_destination_identity(destination) for destination in destinations}
    )
    deadline = time.monotonic() + timeout_seconds
    locked_descriptors: list[tuple[Path, int]] = []
    primary_error: BaseException | None = None
    try:
        for identity in identities:
            lock_path = _publication_lock_path(identity)
            flags = os.O_CREAT | os.O_RDWR
            if hasattr(os, "O_BINARY"):
                flags |= os.O_BINARY
            descriptor = os.open(lock_path, flags, 0o600)
            if os.name == "nt" and os.fstat(descriptor).st_size == 0:
                os.write(descriptor, b"\0")
                os.fsync(descriptor)
            while True:
                try:
                    _acquire_descriptor_lock(descriptor)
                except OSError as error:
                    if not _lock_is_contended(error):
                        os.close(descriptor)
                        raise
                    if time.monotonic() >= deadline:
                        os.close(descriptor)
                        raise PublicationLockTimeoutError(
                            "timed out acquiring package publication lock for "
                            f"{identity}"
                        ) from error
                    time.sleep(
                        min(PUBLICATION_LOCK_POLL_SECONDS, max(0.0, deadline - time.monotonic()))
                    )
                    continue
                locked_descriptors.append((lock_path, descriptor))
                break
        yield
    except BaseException as error:
        primary_error = error
        raise
    finally:
        release_failures = _release_publication_locks(locked_descriptors)
        if release_failures:
            if primary_error is not None:
                try:
                    setattr(
                        primary_error,
                        "publication_lock_release_failures",
                        release_failures,
                    )
                except BaseException:
                    pass
            else:
                release_error = OSError(
                    "package publication completed with lock-release failures"
                )
                setattr(
                    release_error,
                    "publication_lock_release_failures",
                    release_failures,
                )
                raise release_error


def path_entry_exists(path: Path) -> bool:
    """Return whether *path* exists without following a dangling symlink."""

    return path.exists() or path.is_symlink()


def allocate_owned_path(destination: Path, purpose: str, owner_label: str) -> Path:
    """Allocate a same-directory path owned by one package publication."""

    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, raw_path = tempfile.mkstemp(
        prefix=f".{destination.name}.{owner_label}-{purpose}-",
        dir=destination.parent,
    )
    os.close(descriptor)
    return Path(raw_path)


def _exception_record(error: BaseException) -> dict[str, str]:
    return {"type": type(error).__name__, "message": str(error)}


def _unlink_non_directory(path: Path) -> None:
    if not path_entry_exists(path):
        return
    if path.is_dir() and not path.is_symlink():
        raise IsADirectoryError(f"refusing to remove directory: {path}")
    path.unlink()


def cleanup_owned_paths(paths: list[Path]) -> list[dict[str, str]]:
    """Best-effort cleanup that records every failure and continues."""

    failures: list[dict[str, str]] = []
    for path in paths:
        try:
            _unlink_non_directory(path)
        except BaseException as error:
            failures.append({"path": str(path), **_exception_record(error)})
    return failures


def _transition_record(state: dict[str, Any]) -> dict[str, Any]:
    return {
        "destination": str(state["destination"]),
        "staged": str(state["staged"]),
        "prior_entry_existed": state["prior_entry_existed"],
        "backup": None if state["backup"] is None else str(state["backup"]),
        "backup_completed": state["backup_completed"],
        "publication_completed": state["publication_completed"],
        "published_entry_removed": state["published_entry_removed"],
        "backup_restored": state["backup_restored"],
    }


def _recovery_record(
    states: list[dict[str, Any]],
    primary_error: BaseException,
    rollback_failures: list[dict[str, str]],
    cleanup_failures: list[dict[str, str]],
) -> dict[str, Any]:
    unrestored_backups = [
        {
            "destination": str(state["destination"]),
            "backup": str(state["backup"]),
        }
        for state in states
        if state["backup_completed"]
        and not state["backup_restored"]
        and state["backup"] is not None
        and path_entry_exists(state["backup"])
    ]
    return {
        "schema_version": RECOVERY_SCHEMA_VERSION,
        "primary_error": _exception_record(primary_error),
        "transitions": [_transition_record(state) for state in states],
        "rollback_failures": rollback_failures,
        "cleanup_failures": cleanup_failures,
        "unrestored_backups": unrestored_backups,
    }


def publish_staged_outputs(
    staged_outputs: list[tuple[Path, Path]], *, owner_label: str
) -> None:
    """Publish all staged outputs atomically per path and recover as one batch.

    Recovery covers Python exceptions and process-level interrupts delivered as
    ``BaseException``. It cannot make guarantees across kernel or power loss.
    """

    with _publication_locks(
        [destination for destination, _staged in staged_outputs]
    ):
        _publish_staged_outputs_locked(staged_outputs, owner_label=owner_label)


def _publish_staged_outputs_locked(
    staged_outputs: list[tuple[Path, Path]], *, owner_label: str
) -> None:
    """Publish one batch while its complete destination lock set is held."""

    states: list[dict[str, Any]] = []
    for destination, staged in staged_outputs:
        if destination.is_dir() and not destination.is_symlink():
            raise IsADirectoryError(
                f"destination must not be a directory: {destination}"
            )
        states.append(
            {
                "destination": destination,
                "staged": staged,
                "prior_entry_existed": path_entry_exists(destination),
                "backup": None,
                "backup_completed": False,
                "publication_completed": False,
                "published_entry_removed": False,
                "backup_restored": False,
            }
        )

    try:
        for state in states:
            if not state["prior_entry_existed"]:
                continue
            destination = state["destination"]
            backup = allocate_owned_path(destination, "backup", owner_label)
            state["backup"] = backup
            backup.unlink()
            try:
                os.replace(destination, backup)
            except BaseException:
                if path_entry_exists(backup) and not path_entry_exists(destination):
                    state["backup_completed"] = True
                raise
            state["backup_completed"] = True

        for state in states:
            destination = state["destination"]
            staged = state["staged"]
            try:
                os.replace(staged, destination)
            except BaseException:
                if not path_entry_exists(staged) and path_entry_exists(destination):
                    state["publication_completed"] = True
                raise
            state["publication_completed"] = True
    except BaseException as primary_error:
        rollback_failures: list[dict[str, str]] = []
        for state in reversed(states):
            destination = state["destination"]
            if state["publication_completed"]:
                try:
                    _unlink_non_directory(destination)
                except BaseException as error:
                    if not path_entry_exists(destination):
                        state["published_entry_removed"] = True
                    else:
                        rollback_failures.append(
                            {
                                "operation": "remove_published_entry",
                                "path": str(destination),
                                **_exception_record(error),
                            }
                        )
                else:
                    state["published_entry_removed"] = True

            backup = state["backup"]
            if not state["backup_completed"] or backup is None:
                continue
            if path_entry_exists(destination):
                rollback_failures.append(
                    {
                        "operation": "restore_backup",
                        "path": str(destination),
                        "type": "DestinationOccupied",
                        "message": "published destination could not be cleared",
                    }
                )
                continue
            try:
                os.replace(backup, destination)
            except BaseException as error:
                if not path_entry_exists(backup) and path_entry_exists(destination):
                    state["backup_restored"] = True
                else:
                    rollback_failures.append(
                        {
                            "operation": "restore_backup",
                            "path": str(destination),
                            "backup": str(backup),
                            **_exception_record(error),
                        }
                    )
            else:
                state["backup_restored"] = True

        protected_backups = {
            state["backup"]
            for state in states
            if state["backup_completed"] and not state["backup_restored"]
        }
        cleanup_candidates = [state["staged"] for state in states]
        cleanup_candidates.extend(
            state["backup"]
            for state in states
            if state["backup"] is not None
            and state["backup"] not in protected_backups
        )
        cleanup_failures = cleanup_owned_paths(cleanup_candidates)
        record = _recovery_record(
            states,
            primary_error,
            rollback_failures,
            cleanup_failures,
        )

        recovery_complete = all(
            (
                not state["backup_completed"] or state["backup_restored"]
                if state["prior_entry_existed"]
                else True
            )
            and (
                state["published_entry_removed"]
                if state["publication_completed"]
                else True
            )
            for state in states
        )
        if recovery_complete:
            if cleanup_failures:
                try:
                    setattr(primary_error, "publication_recovery_record", record)
                except BaseException:
                    pass
            raise
        raise PublicationRecoveryError(record) from primary_error

    cleanup_candidates = [state["staged"] for state in states]
    cleanup_candidates.extend(
        state["backup"] for state in states if state["backup"] is not None
    )
    cleanup_failures = cleanup_owned_paths(cleanup_candidates)
    if cleanup_failures:
        cleanup_error = OSError("package publication completed with cleanup failures")
        record = {
            "schema_version": RECOVERY_SCHEMA_VERSION,
            "primary_error": _exception_record(cleanup_error),
            "transitions": [_transition_record(state) for state in states],
            "rollback_failures": [],
            "cleanup_failures": cleanup_failures,
            "unrestored_backups": [],
        }
        raise PublicationRecoveryError(record) from cleanup_error
