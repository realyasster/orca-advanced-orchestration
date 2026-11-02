"""Error types with actionable messages for the installation manager."""


class InstallationError(Exception):
    """A user-facing failure. The CLI prints the message and exits with 1."""


class BundleError(InstallationError):
    """The change bundle is missing, malformed, or failed a hash check."""


class CheckoutError(InstallationError):
    """The target is not a supported Orca source checkout."""


class PathSafetyError(InstallationError):
    """A managed path would escape the checkout or traverse a link."""


class StateError(InstallationError):
    """The installation record is missing pieces or is invalid."""


class LockError(InstallationError):
    """Another mutation holds the checkout lock, or a lock cannot be trusted."""


class RecoveryRequiredError(InstallationError):
    """Automatic recovery is unsafe; the user must inspect the record and files."""


class InterruptedOperationError(InstallationError):
    """A previous operation was reconciled; the requested command must be re-run."""
