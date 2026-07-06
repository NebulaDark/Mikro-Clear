"""Deprecated compatibility shim for Suricata event helpers."""

from mikroclear.suricata.events import EventFilterDecision, should_process_event, validate_event

__all__ = ["EventFilterDecision", "should_process_event", "validate_event"]
