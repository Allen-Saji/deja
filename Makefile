.PHONY: p3-lambda-timeout p3-crdb-node-failure

p3-lambda-timeout:
	.venv/bin/python scripts/p3_lambda_timeout.py

p3-crdb-node-failure:
	.venv/bin/python scripts/p3_crdb_node_failure.py
