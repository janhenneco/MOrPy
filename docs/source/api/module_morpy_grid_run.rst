morpy.grid_run module
=====================

Module
-------

.. automodule:: morpy.grid_run
   :members:
   :noindex:

Classes
--------

.. autosummary::
   :nosignatures:

   GridRunHandle
   GridRunItem
   GridRunResult
   ReconcileSummary
   RestartPolicy

Functions
---------

.. autosummary::
   :nosignatures:

   _cancel_pending_items
   _cancel_running_item
   _cancelled_result
   _cleanup_tracker_after_grid
   _coerce_model_state
   _collect_run_result
   _exception_result
   _is_timeout_reason
   _mark_model_restart
   _mark_recovered_cancelled
   _normalize_path
   _pid_exists
   _poll_repo_stop_request
   _prepare_tracker_for_grid
   _reconcile_items_with_repository
   _schedule_decision_for_state
   _setdefault_inc
   _should_mark_restart
   _stop_from_repository
   _summarize
   _terminate_pid_tree
   _wait_pid_exit
   cancel_model
   find_active_model_id_by_pid
   launch_grid
   run_grid
   run_models_local
   run_models_mpi
   stop_grid
   wait_for_grid
