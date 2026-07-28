.PHONY: lambda-timeout-acceptance crdb-node-failure-acceptance

lambda-timeout-acceptance:
	.venv/bin/python scripts/lambda_timeout_acceptance.py

crdb-node-failure-acceptance:
	.venv/bin/python scripts/crdb_node_failure_acceptance.py
