---
id: docflow
name: "DocFlow"
tagline: "Event-driven serverless document pipeline on AWS — Lambda, S3, Step Functions"
role_families: [cloud, devops, backend]
skills:
  core: [aws, lambda_serverless, s3, cloud_iam, cloudformation]
  supporting: [ec2, vpc_networking_cloud, secrets_mgmt, python, nosql, rest_api]
  touch: [github_actions, kafka_streaming]
est_days: 2
lab_cost: "< $2 — AWS free tier (Lambda, S3, DynamoDB, SQS); Textract per-page cost for tests"
---

# DocFlow — Serverless Document Processing on AWS

## Problem
Back-office teams (invoices, onboarding forms, claims) still download PDFs, read them and
type values into a system. Always-on servers built to automate this sit idle 95% of the
time and still fall over at month-end spikes.

## Why it matters (impact)
- Pay-per-use: idle cost ≈ $0, scales to thousands of documents at month-end automatically.
- Manual data entry (~4 min/document) → seconds; at 2,000 docs/month ≈ 130 hours saved.
- Least-privilege IAM per function and encryption everywhere pass security review.

## Approach
1. Upload via pre-signed S3 URL from a small API Gateway + Lambda endpoint (Cognito auth).
2. S3 event → SQS (buffer, DLQ) → Step Functions workflow:
   classify → extract (Textract) → validate → persist to DynamoDB → notify (SNS/SES).
3. Failure handling: retries with backoff, DLQ + redrive, idempotency keys.
4. Security: one IAM role per function (least privilege), KMS-encrypted buckets/tables,
   Secrets Manager for third-party keys, VPC endpoints for private access, S3 Block Public Access.
5. IaC with AWS SAM/CDK (CloudFormation under the hood); GitHub Actions with OIDC
   (no long-lived keys) deploys dev/prod stacks.
6. Observability: structured logs, X-Ray tracing, CloudWatch dashboard + alarms on DLQ depth.
7. Cost report: measured cost per 1,000 documents.

## Architecture
```
client ─> API GW + Lambda (pre-signed URL) ─> S3 (KMS) ─event─> SQS (+DLQ)
                                                          └─> Step Functions:
                                          classify ─> Textract ─> validate ─> DynamoDB ─> SNS/SES
GitHub Actions (OIDC) ─> SAM/CDK ─> CloudFormation stacks (dev/prod)      X-Ray · CloudWatch alarms
```

## Interview-ready core (day 1)
S3 → SQS → Lambda → Textract → DynamoDB with DLQ, least-privilege roles, SAM template,
deployed by GitHub Actions via OIDC.

## Full build plan
| Day | Deliverable |
|---|---|
| 1 | Core pipeline, IAM, SAM/CDK, OIDC deploy |
| 2 | Step Functions orchestration, API + Cognito, X-Ray, alarms, load test + cost report |

## Target metrics (measure; replace with actuals)
- 1,000-document burst processed in < 5 min with 0 lost documents (DLQ redrive verified).
- p95 end-to-end per document < 8 s.
- Measured cost ≈ $X per 1,000 docs (compute; exclude Textract); idle cost $0.
- 0 long-lived AWS keys in CI; IAM Access Analyzer: 0 findings.

## Draft resume bullets
- Built an event-driven document processing pipeline on AWS (S3, SQS, Lambda, Step Functions, Textract, DynamoDB) that processed a 1,000-document burst in under 5 minutes with zero lost messages via DLQ redrive.
- Enforced least-privilege IAM per function, KMS encryption, VPC endpoints and Secrets Manager, with zero findings from IAM Access Analyzer.
- Deployed all infrastructure as code with AWS SAM/CloudFormation through GitHub Actions using OIDC federation, eliminating long-lived credentials, with X-Ray tracing and CloudWatch alarms on queue depth.

## Likely interview questions
- Lambda cold starts, concurrency limits, and when not to use Lambda.
- SQS standard vs FIFO, visibility timeout, DLQ.
- IAM policy evaluation logic (explicit deny, SCPs, permission boundaries).
- How OIDC federation from GitHub to AWS works.
