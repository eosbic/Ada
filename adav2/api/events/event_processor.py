from api.services.agent_runner import run_agent


async def process_event(event, agent):

    empresa_id = event["empresa_id"]

    if event["event_type"] == "chat_message":

        message = event["payload"]["message"]

        response = await run_agent(
            message,
            empresa_id,
            agent
        )

        print("IA RESPONSE:", response)