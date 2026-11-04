"""Reconcile a journal left behind by an interrupted install or uninstall."""

from __future__ import annotations

from typing import Optional

from .errors import RecoveryRequiredError, StateError
from .gitutil import Checkout
from .store import Store


def reconcile_locked(store: Store, checkout: Checkout, command: str) -> Optional[str]:
    """Reconcile the current journal while the caller holds the lock.

    Returns the kind of interrupted operation that was completed, or ``None``
    when there was nothing to do. The caller must not start a new mutation in
    the same invocation; the user re-runs the command after reconciliation.
    """

    state = store.require_state()
    record = state.installation
    if record is None:
        return None
    if record.status in ("installed", "uninstalled"):
        return None
    if record.status == "recovery_required":
        raise RecoveryRequiredError(
            f"The installation is in recovery_required state. Inspect {store.base_dir} "
            "before changing anything."
        )
    if record.status == "installing":
        from .installer import rollback_interrupted_install

        rollback_interrupted_install(store, checkout, record)
        return "install"
    if record.status == "updating":
        from .updater import rollback_interrupted_update

        rollback_interrupted_update(store, checkout, record)
        return "update"
    if record.status == "uninstalling":
        from .uninstaller import resume_interrupted_uninstall

        resume_interrupted_uninstall(store, checkout, record)
        return "uninstall"
    raise StateError(f"Unknown installation status: {record.status}")
