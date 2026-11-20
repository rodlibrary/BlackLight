"""Preservica Blacklight ingest pipeline.

Harvests public records from Preservica (OAI-PMH for descriptive metadata, the
Entity API for the folder hierarchy, the Content API for thumbnails) and writes
them to Solr as ``Record`` objects (see ``ingest.core``). Only
``Record.to_solr()`` decides Solr field names, so the Blacklight catalog
controller and the index stay in step.
"""

__version__ = "0.1.0"
