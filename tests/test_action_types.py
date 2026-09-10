from app.action_types import (
    ACTION_TYPES, ACTION_TYPE_BY_ID, CATALOG_VERSION, FALLBACK_IDS,
    ActionType, Predicate, catalog_contract, evaluate_predicate,
    fallback_option_descriptors, validate_batch_grouping,
)
from app.api import ontology_contract
from app.ontology.enums import ObjectType


def test_catalog_is_versioned_read_only_schema_and_reuses_fields():
    contract = catalog_contract()
    assert contract['version'] == CATALOG_VERSION
    assert ObjectType.ACTION_TYPE.value == 'ActionType'
    assert len(contract['items']) == len(ACTION_TYPES) == len(ACTION_TYPE_BY_ID)
    assert all(ActionType.model_validate(item) for item in contract['items'])
    assert all(item.decision_inputs == ActionType.model_validate(item.model_dump()).decision_inputs
               for item in ACTION_TYPES)


def test_public_ontology_contract_exposes_action_catalog_and_decision_compatibility():
    contract = ontology_contract()
    assert contract['contract_version'] == 'ontology-v1.3'
    assert contract['action_types']['version'] == CATALOG_VERSION
    assert 'FieldDescriptor' in contract['action_types']['schema']['$defs']
    assert contract['task_decision_contract'] == {
        'current': 'decision-v2', 'read_only_compatibility': ['decision-v1']
    }
    assert {'execute_task_action', 'revoke_task_action'} <= set(contract['commands'])


def test_five_fallbacks_have_concrete_verbs_and_never_grant_accounting_use():
    assert tuple(item.id for item in ACTION_TYPES if item.fallback) == FALLBACK_IDS
    options = fallback_option_descriptors()
    assert [item['id'] for item in options] == list(FALLBACK_IDS)
    assert len({item['label'] for item in options}) == 5
    assert all(item['label'] not in {'确认', '处理', '提交'} for item in options)
    assert all(effect['grants_accounting_usable'] is False
               for item in options for effect in item['effects'])


def test_predicate_unknown_or_invalid_input_fails_closed():
    assert evaluate_predicate(Predicate(op='EQ', field='kind', value='ISSUE'), {'kind': 'ISSUE'})
    assert not evaluate_predicate(Predicate(op='EQ', field='missing', value='ISSUE'), {'kind': 'ISSUE'})
    assert not evaluate_predicate({'op': 'NEW_OPERATOR', 'field': 'kind'}, {'kind': 'ISSUE'})
    assert not evaluate_predicate(Predicate(op='ALL', children=[]), {})
    assert not evaluate_predicate(Predicate(op='NOT', children=[]), {})


def test_batch_actions_require_declared_grouping_keys():
    assert validate_batch_grouping('confirm_statement_account', ['account_id'])
    assert not validate_batch_grouping('confirm_statement_account', ['bank_name'])
    assert validate_batch_grouping('confirm_bill_business',
                                   ['business_kind', 'business_period', 'account_name'])
    assert not validate_batch_grouping('confirm_bill_business', ['business_kind'])
    assert not validate_batch_grouping('record_judgement', [])
