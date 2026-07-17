"""Shared exception hierarchy for run, orchestration, and persistence layers.

This module defines domain-specific exception classes used to distinguish
preflight validation errors, launch/runtime failures, timeout failures,
and persistence-related failures.
"""

class MesaRunnerError(Exception):
    pass

class RunPreflightError(MesaRunnerError):
    pass

class ModelPathMissingError(RunPreflightError):
    pass

class RunScriptMissingError(RunPreflightError):
    pass

class ExecutableMissingError(RunPreflightError):
    pass

class RunLaunchError(MesaRunnerError):
    pass

class RunTimeoutError(MesaRunnerError):
    pass

class PersistenceError(MesaRunnerError):
    pass