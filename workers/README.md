# workers/

Lambda functions that run in the background (added in later phases):

- `process_upload` (Phase 4): S3 upload -> SQS -> Lambda. Runs `core.retrieval.ingest_file`
  and `match_file_to_concepts` so big files don't slow down the website.
- `review_reminders` (Phase 7): EventBridge (daily) -> Lambda -> SES email
  "You have N reviews due today".

They import from `core/`, the same code the website and MCP server use.
