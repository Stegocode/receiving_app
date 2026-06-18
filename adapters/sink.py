"""
Owns: result sink adapter — posts receiving outcomes to the project management board.
Must not: import core.ports directly — implement the ResultSink protocol concretely.
May import: core.schema, core.errors, config, requests, logging.

Crash-safety invariant: a crash at any step in process_scan, on retry, neither
double-emits nor loses the record. The caller guards with was_emitted before calling
emit; the sink deduplicates on receiving_id internally.
"""
