"""S3 ObjectCreated/Removed → Bedrock KB StartIngestionJob trigger."""

import logging
import os
import time

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

bedrock_agent = boto3.client("bedrock-agent")

KNOWLEDGE_BASE_ID = os.environ["KNOWLEDGE_BASE_ID"]

_last_trigger = 0
_DEBOUNCE_SECONDS = 20
_data_source_id_cache = None


def get_data_source_id() -> str:
    """Lookup the (single) S3 data source for this KB."""
    global _data_source_id_cache
    if _data_source_id_cache:
        return _data_source_id_cache
    resp = bedrock_agent.list_data_sources(knowledgeBaseId=KNOWLEDGE_BASE_ID)
    summaries = resp.get("dataSourceSummaries", [])
    if not summaries:
        raise RuntimeError(f"No data source found for KB {KNOWLEDGE_BASE_ID}")
    _data_source_id_cache = summaries[0]["dataSourceId"]
    logger.info(f"Resolved data source id: {_data_source_id_cache}")
    return _data_source_id_cache


def handler(event, context):
    global _last_trigger

    records = event.get("Records", [])
    changed = [r.get("s3", {}).get("object", {}).get("key", "") for r in records]
    logger.info(f"S3 changes detected: {changed}")

    now = time.time()
    if now - _last_trigger < _DEBOUNCE_SECONDS:
        logger.info(f"Debounced — last trigger {now - _last_trigger:.1f}s ago")
        return {"status": "debounced"}

    _last_trigger = now

    ds_id = get_data_source_id()
    resp = bedrock_agent.start_ingestion_job(
        knowledgeBaseId=KNOWLEDGE_BASE_ID,
        dataSourceId=ds_id,
        description=f"Auto-reindex triggered by S3 change: {changed[0] if changed else 'unknown'}",
    )
    job_id = resp["ingestionJob"]["ingestionJobId"]
    logger.info(f"Started ingestion job: {job_id}")
    return {"status": "started", "ingestionJobId": job_id}
