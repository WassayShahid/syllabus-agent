"""CloudWatch Embedded Metric Format: one JSON log line becomes metrics + a searchable log."""
import json
import time

NAMESPACE = "SyllabusAgent"


def emit(operation, metrics, **properties):
    """metrics: {"InputTokens": 123, ...} (all Count). properties: extra searchable fields."""
    print(json.dumps({
        "_aws": {
            "Timestamp": int(time.time() * 1000),
            "CloudWatchMetrics": [{
                "Namespace": NAMESPACE,
                "Dimensions": [["Operation"]],
                "Metrics": [{"Name": name, "Unit": "Count"} for name in metrics],
            }],
        },
        "Operation": operation,
        **metrics,
        **properties,
    }))
