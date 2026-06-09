"""Cortex ingestion workers (arq). Pull jobs from the Redis queue and run the
per-artifact pipeline. Priority lanes: realtime > backfill > reprocess.
See docs/INGESTION.md §2.
"""
