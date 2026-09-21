# -*- coding: utf-8 -*-
import sys, json
sys.path.insert(0, '.')

from core.db import init_db
init_db()

from core.self_optimize import ab_test_mgr, optimization_engine, prompt_version_mgr

# Test create experiment
exp = ab_test_mgr.create_experiment('Test AB', 'Plan A', 'Plan B', kind='prompt')
print(f'Created experiment: {exp["id"]} - {exp["name"]}')

# Test list experiments
exps = ab_test_mgr.list_experiments()
print(f'Listed experiments: {len(exps)}')

# Test update experiment
updated = ab_test_mgr.update_experiment(exp['id'], status='running')
print(f'Updated experiment status: {updated["status"]}')

# Test delete experiment
deleted = ab_test_mgr.delete_experiment(exp['id'])
print(f'Deleted experiment: {deleted}')

# Test suggestions
suggestions = optimization_engine.list_suggestions()
print(f'Suggestions: {len(suggestions)}')

# Test prompt versions
versions = prompt_version_mgr.list_versions()
print(f'Prompt versions: {len(versions)}')

print('\nAll self_optimize methods working!')
