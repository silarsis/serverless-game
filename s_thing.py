import serverless_sdk
sdk = serverless_sdk.SDK(
    tenant_id='silarsis',
    application_name='serverless-game',
    app_uid='2fr7rMcrbxv9vMnDB1',
    tenant_uid='9bbC99dJ0Z2C6yDkpd',
    deployment_uid='8c2abce8-a897-427e-8fc9-a76d72dbd780',
    service_name='serverless-game',
    stage_name='dev',
    plugin_version='3.2.7'
)
handler_wrapper_kwargs = {'function_name': 'serverless-game-dev-thing', 'timeout': 6}
try:
    user_handler = serverless_sdk.get_user_handler('aspects/thing.handler')
    handler = sdk.handler(user_handler, **handler_wrapper_kwargs)
except Exception as error:
    e = error
    def error_handler(event, context):
        raise e
    handler = sdk.handler(error_handler, **handler_wrapper_kwargs)
