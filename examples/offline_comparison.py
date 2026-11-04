"""Synthetic API demonstration: no model, credentials, cloud, or measured result."""
from dataclasses import replace
import json
from rsilab import Agent, FrozenJSON, Manifest, Provenance, RunResult, Split, Task, compare, digest


def main():
    task = Task('demo-task', 'demo-family', Split.DEV, 'Synthetic demonstration', FrozenJSON({}))
    identity = digest({'synthetic': True})
    agent = Agent('parent', 'synthetic/model', '0' * 40, identity, identity)
    provenance = Provenance(identity, identity, identity, identity, FrozenJSON({'runtime': 'synthetic'}), 'none')
    parent = Manifest('parent-run', agent, (task,), (42,), FrozenJSON({'max_tokens': 128}), FrozenJSON({'temperature': 0}), provenance)
    candidate = replace(parent, run_id='candidate-run', agent=replace(agent, id='candidate', adapter_sha256=digest('synthetic-adapter')))
    def result(manifest, score):
        return RunResult(manifest.run_id, manifest.agent.id, task.id, 42, 'completed', FrozenJSON({'synthetic': True}), score)
    report = compare(parent, candidate, [result(parent, 0)], [result(candidate, 1)])
    assert report['matched'] and not report['promoted']
    print(json.dumps({'synthetic_example': True, 'comparison': report}, indent=2))


if __name__ == '__main__':
    main()
