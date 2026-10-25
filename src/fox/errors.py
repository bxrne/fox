"""Failures a contract can raise. Each class says who broke the deal."""


class ContractError(Exception):
    """A fox contract failed."""


class PreconditionError(ContractError):
    """The caller broke ``requires``. The function body did not run."""


class PostconditionError(ContractError):
    """The function broke ``ensures``."""


class FailedClaim(ContractError):
    """``fox.claim`` received a false condition."""


class EffectError(ContractError):
    """An effect is undeclared, or a generated call has no boundary handler."""
