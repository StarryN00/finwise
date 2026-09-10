from app.ontology.contracts import Scope
from app.ontology.enums import ObjectType


def test_display_context_uses_book_name_and_preserves_scope(client, scope):
    service, typed = client.app.state.service, Scope(**scope)
    service.create_scope(typed)
    before = service.store.get_object(service._book_object_id(typed), typed)
    overview = client.post('/api/v1/workbench', json={'scope': scope}).json()
    assert overview['display_context'] == {'company_name': None, 'business_license_number': None, 'ledger_name': '主账套'}
    assert overview['scope'] == scope
    assert service.portfolio([typed])['scopes'][0]['display_context'] == overview['display_context']
    assert service.store.get_object(before['object_id'], typed) == before


def test_custom_labels_and_license_are_scoped(client, scope):
    service, typed = client.app.state.service, Scope(**scope)
    obj = service.create_scope(typed)
    service.store.create_object(ObjectType.SCOPE.value, typed,
        {**obj['data'], 'enterprise_profile': {'name': '测试企业', 'business_license_number': 'TEST-LICENSE-001'}}, object_id=obj['object_id'])
    book = service.store.get_object(service._book_object_id(typed), typed)
    service.store.create_object(ObjectType.ACCOUNTING_BOOK.value, typed,
        {**book['data'], 'name': '业务二账套'}, object_id=book['object_id'])
    other = Scope(**{**scope, 'tenant_id': 'other'})
    service.create_scope(other)
    assert service.display_context(typed) == {'company_name': '测试企业', 'business_license_number': 'TEST-LICENSE-001', 'ledger_name': '业务二账套'}
    assert service.display_context(other)['business_license_number'] is None
    assert service.display_context(other)['ledger_name'] == '主账套'
    service.store.create_object(ObjectType.ACCOUNTING_BOOK.value, typed,
        {**book['data'], 'name': scope['ledger_id']}, object_id=book['object_id'])
    assert service.display_context(typed)['ledger_name'] == '主账套'
