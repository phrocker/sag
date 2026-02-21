"""Sample conversations for benchmarking in SAG, JSON, and natural language formats."""

# Each conversation is a tuple of (sag_messages, json_equivalent, natural_language)

CONVERSATIONS = [
    # 1. Simple deploy sequence
    {
        "name": "Deploy sequence",
        "sag": [
            'H v 1 id=msg1 src=devops dst=prod ts=1000\nDO deploy("webapp", version=42)',
            'H v 1 id=msg2 src=prod dst=devops ts=1001 corr=msg1\nA deploy.status = "in_progress"',
            'H v 1 id=msg3 src=prod dst=devops ts=1010 corr=msg1\nEVT deployComplete("webapp")',
        ],
        "json": [
            '{"header":{"version":1,"messageId":"msg1","source":"devops","destination":"prod","timestamp":1000},"statements":[{"type":"action","verb":"deploy","args":["webapp"],"namedArgs":{"version":42}}]}',
            '{"header":{"version":1,"messageId":"msg2","source":"prod","destination":"devops","timestamp":1001,"correlation":"msg1"},"statements":[{"type":"assert","path":"deploy.status","value":"in_progress"}]}',
            '{"header":{"version":1,"messageId":"msg3","source":"prod","destination":"devops","timestamp":1010,"correlation":"msg1"},"statements":[{"type":"event","eventName":"deployComplete","args":["webapp"]}]}',
        ],
        "nl": [
            "[devops -> prod] Please deploy the webapp application, version 42.",
            "[prod -> devops] Acknowledged. The deployment of webapp is now in progress.",
            "[prod -> devops] The deployment of webapp has completed successfully.",
        ],
    },
    # 2. Health check with conditional
    {
        "name": "Health check with conditional",
        "sag": [
            "H v 1 id=msg1 src=monitor dst=svc1 ts=2000\nQ health.status",
            'H v 1 id=msg2 src=svc1 dst=monitor ts=2001 corr=msg1\nA health.status = "degraded"',
            'H v 1 id=msg3 src=monitor dst=svc1 ts=2002 corr=msg2\nIF health.status=="degraded" THEN DO restart() ELSE DO noop()',
        ],
        "json": [
            '{"header":{"version":1,"messageId":"msg1","source":"monitor","destination":"svc1","timestamp":2000},"statements":[{"type":"query","expression":"health.status"}]}',
            '{"header":{"version":1,"messageId":"msg2","source":"svc1","destination":"monitor","timestamp":2001,"correlation":"msg1"},"statements":[{"type":"assert","path":"health.status","value":"degraded"}]}',
            '{"header":{"version":1,"messageId":"msg3","source":"monitor","destination":"svc1","timestamp":2002,"correlation":"msg2"},"statements":[{"type":"control","condition":"health.status==\\"degraded\\"","then":{"type":"action","verb":"restart"},"else":{"type":"action","verb":"noop"}}]}',
        ],
        "nl": [
            "[monitor -> svc1] What is the current health status?",
            "[svc1 -> monitor] The health status is degraded.",
            "[monitor -> svc1] Since the health status is degraded, please restart the service. Otherwise, do nothing.",
        ],
    },
    # 3. Multi-agent workflow
    {
        "name": "Multi-agent data pipeline",
        "sag": [
            'H v 1 id=msg1 src=orchestrator dst=ingester ts=3000\nDO ingest("s3://data/batch42") PRIO=HIGH',
            'H v 1 id=msg2 src=ingester dst=orchestrator ts=3010 corr=msg1\nA ingest.rows = 50000; A ingest.status = "complete"',
            'H v 1 id=msg3 src=orchestrator dst=transformer ts=3011 corr=msg2\nDO transform("batch42", format="parquet")',
            'H v 1 id=msg4 src=transformer dst=orchestrator ts=3050 corr=msg3\nEVT transformComplete("batch42"); A transform.output = "s3://out/batch42.parquet"',
            'H v 1 id=msg5 src=orchestrator dst=validator ts=3051 corr=msg4\nDO validate("s3://out/batch42.parquet", schema="pipeline_v2")',
            'H v 1 id=msg6 src=validator dst=orchestrator ts=3060 corr=msg5\nA validation.passed = true; A validation.rows = 50000',
        ],
        "json": [
            '{"header":{"version":1,"messageId":"msg1","source":"orchestrator","destination":"ingester","timestamp":3000},"statements":[{"type":"action","verb":"ingest","args":["s3://data/batch42"],"priority":"HIGH"}]}',
            '{"header":{"version":1,"messageId":"msg2","source":"ingester","destination":"orchestrator","timestamp":3010,"correlation":"msg1"},"statements":[{"type":"assert","path":"ingest.rows","value":50000},{"type":"assert","path":"ingest.status","value":"complete"}]}',
            '{"header":{"version":1,"messageId":"msg3","source":"orchestrator","destination":"transformer","timestamp":3011,"correlation":"msg2"},"statements":[{"type":"action","verb":"transform","args":["batch42"],"namedArgs":{"format":"parquet"}}]}',
            '{"header":{"version":1,"messageId":"msg4","source":"transformer","destination":"orchestrator","timestamp":3050,"correlation":"msg3"},"statements":[{"type":"event","eventName":"transformComplete","args":["batch42"]},{"type":"assert","path":"transform.output","value":"s3://out/batch42.parquet"}]}',
            '{"header":{"version":1,"messageId":"msg5","source":"orchestrator","destination":"validator","timestamp":3051,"correlation":"msg4"},"statements":[{"type":"action","verb":"validate","args":["s3://out/batch42.parquet"],"namedArgs":{"schema":"pipeline_v2"}}]}',
            '{"header":{"version":1,"messageId":"msg6","source":"validator","destination":"orchestrator","timestamp":3060,"correlation":"msg5"},"statements":[{"type":"assert","path":"validation.passed","value":true},{"type":"assert","path":"validation.rows","value":50000}]}',
        ],
        "nl": [
            "[orchestrator -> ingester] HIGH PRIORITY: Please ingest data from s3://data/batch42.",
            "[ingester -> orchestrator] Ingestion complete. 50000 rows ingested from batch42.",
            "[orchestrator -> transformer] Please transform batch42 data into parquet format.",
            "[transformer -> orchestrator] Transformation of batch42 complete. Output written to s3://out/batch42.parquet.",
            "[orchestrator -> validator] Please validate the file at s3://out/batch42.parquet against schema pipeline_v2.",
            "[validator -> orchestrator] Validation passed. All 50000 rows conform to the schema.",
        ],
    },
    # 4. Error handling flow
    {
        "name": "Error handling flow",
        "sag": [
            'H v 1 id=msg1 src=client dst=api ts=4000\nDO createUser("john", email="john@example.com")',
            'H v 1 id=msg2 src=api dst=client ts=4001 corr=msg1\nERR DUPLICATE_EMAIL "User with email john@example.com already exists"',
            'H v 1 id=msg3 src=client dst=api ts=4002 corr=msg2\nDO createUser("john", email="john2@example.com")',
            'H v 1 id=msg4 src=api dst=client ts=4003 corr=msg3\nA user.id = "usr_42"; EVT userCreated("john")',
        ],
        "json": [
            '{"header":{"version":1,"messageId":"msg1","source":"client","destination":"api","timestamp":4000},"statements":[{"type":"action","verb":"createUser","args":["john"],"namedArgs":{"email":"john@example.com"}}]}',
            '{"header":{"version":1,"messageId":"msg2","source":"api","destination":"client","timestamp":4001,"correlation":"msg1"},"statements":[{"type":"error","errorCode":"DUPLICATE_EMAIL","message":"User with email john@example.com already exists"}]}',
            '{"header":{"version":1,"messageId":"msg3","source":"client","destination":"api","timestamp":4002,"correlation":"msg2"},"statements":[{"type":"action","verb":"createUser","args":["john"],"namedArgs":{"email":"john2@example.com"}}]}',
            '{"header":{"version":1,"messageId":"msg4","source":"api","destination":"client","timestamp":4003,"correlation":"msg3"},"statements":[{"type":"assert","path":"user.id","value":"usr_42"},{"type":"event","eventName":"userCreated","args":["john"]}]}',
        ],
        "nl": [
            "[client -> api] Create a new user named john with email john@example.com.",
            "[api -> client] Error: A user with email john@example.com already exists.",
            "[client -> api] Create a new user named john with email john2@example.com instead.",
            "[api -> client] User created successfully. User ID is usr_42.",
        ],
    },
    # 5. Monitoring with policy
    {
        "name": "Monitoring with guardrails",
        "sag": [
            "H v 1 id=msg1 src=monitor dst=scaler ts=5000\nDO scaleUp(replicas=5) P:autoscale PRIO=HIGH BECAUSE cpu>80",
            "H v 1 id=msg2 src=scaler dst=monitor ts=5010 corr=msg1\nA cluster.replicas = 5; EVT scaled(5)",
            "H v 1 id=msg3 src=monitor dst=scaler ts=5020\nQ cluster.metrics WHERE cpu>50",
            'H v 1 id=msg4 src=scaler dst=monitor ts=5021 corr=msg3\nA cluster.cpu = 45; A cluster.memory = 62; A cluster.status = "healthy"',
        ],
        "json": [
            '{"header":{"version":1,"messageId":"msg1","source":"monitor","destination":"scaler","timestamp":5000},"statements":[{"type":"action","verb":"scaleUp","namedArgs":{"replicas":5},"policy":"autoscale","priority":"HIGH","reason":"cpu>80"}]}',
            '{"header":{"version":1,"messageId":"msg2","source":"scaler","destination":"monitor","timestamp":5010,"correlation":"msg1"},"statements":[{"type":"assert","path":"cluster.replicas","value":5},{"type":"event","eventName":"scaled","args":[5]}]}',
            '{"header":{"version":1,"messageId":"msg3","source":"monitor","destination":"scaler","timestamp":5020},"statements":[{"type":"query","expression":"cluster.metrics","constraint":"cpu>50"}]}',
            '{"header":{"version":1,"messageId":"msg4","source":"scaler","destination":"monitor","timestamp":5021,"correlation":"msg3"},"statements":[{"type":"assert","path":"cluster.cpu","value":45},{"type":"assert","path":"cluster.memory","value":62},{"type":"assert","path":"cluster.status","value":"healthy"}]}',
        ],
        "nl": [
            "[monitor -> scaler] HIGH PRIORITY: Scale up to 5 replicas under autoscale policy because CPU usage is above 80%.",
            "[scaler -> monitor] Scaled cluster to 5 replicas. Scaling event recorded.",
            "[monitor -> scaler] Query cluster metrics where CPU is above 50%.",
            "[scaler -> monitor] Current metrics: CPU at 45%, memory at 62%, cluster status is healthy.",
        ],
    },
    # 6-10: Additional shorter conversations for breadth
    {
        "name": "Simple query-response",
        "sag": [
            "H v 1 id=m1 src=a dst=b ts=100\nQ version",
            'H v 1 id=m2 src=b dst=a ts=101 corr=m1\nA version = "2.1.0"',
        ],
        "json": [
            '{"header":{"version":1,"messageId":"m1","source":"a","destination":"b","timestamp":100},"statements":[{"type":"query","expression":"version"}]}',
            '{"header":{"version":1,"messageId":"m2","source":"b","destination":"a","timestamp":101,"correlation":"m1"},"statements":[{"type":"assert","path":"version","value":"2.1.0"}]}',
        ],
        "nl": [
            "[a -> b] What version are you running?",
            "[b -> a] I am running version 2.1.0.",
        ],
    },
    {
        "name": "Batch operations",
        "sag": [
            'H v 1 id=m1 src=ctrl dst=worker ts=200\nDO process("item1"); DO process("item2"); DO process("item3")',
            "H v 1 id=m2 src=worker dst=ctrl ts=210 corr=m1\nA processed = 3; A errors = 0",
        ],
        "json": [
            '{"header":{"version":1,"messageId":"m1","source":"ctrl","destination":"worker","timestamp":200},"statements":[{"type":"action","verb":"process","args":["item1"]},{"type":"action","verb":"process","args":["item2"]},{"type":"action","verb":"process","args":["item3"]}]}',
            '{"header":{"version":1,"messageId":"m2","source":"worker","destination":"ctrl","timestamp":210,"correlation":"m1"},"statements":[{"type":"assert","path":"processed","value":3},{"type":"assert","path":"errors","value":0}]}',
        ],
        "nl": [
            "[ctrl -> worker] Process the following items: item1, item2, item3.",
            "[worker -> ctrl] All 3 items processed successfully with 0 errors.",
        ],
    },
    {
        "name": "Authentication flow",
        "sag": [
            'H v 1 id=m1 src=gateway dst=auth ts=300\nDO authenticate("user42", token="abc123")',
            'H v 1 id=m2 src=auth dst=gateway ts=301 corr=m1\nA auth.valid = true; A auth.role = "admin"; A auth.expires = 3600',
        ],
        "json": [
            '{"header":{"version":1,"messageId":"m1","source":"gateway","destination":"auth","timestamp":300},"statements":[{"type":"action","verb":"authenticate","args":["user42"],"namedArgs":{"token":"abc123"}}]}',
            '{"header":{"version":1,"messageId":"m2","source":"auth","destination":"gateway","timestamp":301,"correlation":"m1"},"statements":[{"type":"assert","path":"auth.valid","value":true},{"type":"assert","path":"auth.role","value":"admin"},{"type":"assert","path":"auth.expires","value":3600}]}',
        ],
        "nl": [
            "[gateway -> auth] Authenticate user42 with token abc123.",
            "[auth -> gateway] Authentication successful. User has admin role. Token expires in 3600 seconds.",
        ],
    },
    {
        "name": "TTL and timeout",
        "sag": [
            "H v 1 id=m1 src=a dst=b ts=400 ttl=10\nDO ping()",
            'H v 1 id=m2 src=b dst=a ts=401 corr=m1\nA alive = true; A latency = "2ms"',
        ],
        "json": [
            '{"header":{"version":1,"messageId":"m1","source":"a","destination":"b","timestamp":400,"ttl":10},"statements":[{"type":"action","verb":"ping"}]}',
            '{"header":{"version":1,"messageId":"m2","source":"b","destination":"a","timestamp":401,"correlation":"m1"},"statements":[{"type":"assert","path":"alive","value":true},{"type":"assert","path":"latency","value":"2ms"}]}',
        ],
        "nl": [
            "[a -> b] Ping (expires in 10 seconds).",
            "[b -> a] Pong. Alive. Latency is 2ms.",
        ],
    },
    {
        "name": "Cascading events",
        "sag": [
            'H v 1 id=m1 src=sensor dst=hub ts=500\nEVT temperatureAlert("zone3", temp=95)',
            'H v 1 id=m2 src=hub dst=cooling ts=501 corr=m1\nDO activateCooling(zone="zone3") PRIO=CRITICAL',
            'H v 1 id=m3 src=cooling dst=hub ts=510 corr=m2\nA cooling.active = true; EVT coolingStarted("zone3")',
        ],
        "json": [
            '{"header":{"version":1,"messageId":"m1","source":"sensor","destination":"hub","timestamp":500},"statements":[{"type":"event","eventName":"temperatureAlert","args":["zone3"],"namedArgs":{"temp":95}}]}',
            '{"header":{"version":1,"messageId":"m2","source":"hub","destination":"cooling","timestamp":501,"correlation":"m1"},"statements":[{"type":"action","verb":"activateCooling","namedArgs":{"zone":"zone3"},"priority":"CRITICAL"}]}',
            '{"header":{"version":1,"messageId":"m3","source":"cooling","destination":"hub","timestamp":510,"correlation":"m2"},"statements":[{"type":"assert","path":"cooling.active","value":true},{"type":"event","eventName":"coolingStarted","args":["zone3"]}]}',
        ],
        "nl": [
            "[sensor -> hub] Temperature alert in zone3: temperature is 95 degrees.",
            "[hub -> cooling] CRITICAL: Activate cooling system in zone3 immediately.",
            "[cooling -> hub] Cooling system activated in zone3. Cooling has started.",
        ],
    },
]
