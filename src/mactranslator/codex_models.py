"""Codex reasoning values shared by the settings UI and protocol adapter."""
EFFORTS = ('none', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max', 'ultra')


def model_choice(model):
    return {'id': model['model'], 'name': model['displayName'],
            'efforts': [e['reasoningEffort'] for e in model.get('supportedReasoningEfforts', [])
                        if e.get('reasoningEffort') in EFFORTS],
            'default_effort': model.get('defaultReasoningEffort'),
            'is_default': bool(model.get('isDefault'))}


async def list_models(client):
    models, cursor = [], None
    for _ in range(20):
        page = await client.call('model/list', {'limit': 100, 'includeHidden': False, 'cursor': cursor})
        models.extend(model_choice(m) for m in page['data'])
        cursor = page.get('nextCursor')
        if not cursor:
            return models
    return models
