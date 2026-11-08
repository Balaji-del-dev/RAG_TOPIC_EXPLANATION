CHAT = "/api/v1/chat/"


def conversation_url(conversation_id) -> str:
    return f"/api/v1/conversations/{conversation_id}/"


def messages_url(conversation_id) -> str:
    return f"/api/v1/conversations/{conversation_id}/messages/"


def chat(client, message: str, conversation_id=None):
    body = {"message": message}
    if conversation_id:
        body["conversation_id"] = str(conversation_id)
    return client.post(CHAT, body, format="json")
