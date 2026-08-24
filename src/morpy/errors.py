"""Shared exception hierarchy for run, orchestration, and persistence layers.

This module defines domain-specific exception classes used to distinguish
preflight validation errors, launch/runtime failures, timeout failures,
and persistence-related failures.
"""

class MorPyError(Exception):
    pass

class RunPreflightError(MorPyError):
    pass

class ModelPathMissingError(RunPreflightError):
    pass

class RunScriptMissingError(RunPreflightError):
    pass

class ExecutableMissingError(RunPreflightError):
    pass

class RunLaunchError(MorPyError):
    pass

class RunTimeoutError(MorPyError):
    pass

class PersistenceError(MorPyError):
    pass