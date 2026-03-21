import asyncio
import json
from sqlalchemy import text

from api.database import AsyncSessionLocal
from api.services.agent_runner import run_agent


async def process_events():

    async with AsyncSessionLocal() as db:

        query = text("""
            SELECT id, empresa_id, event_type, payload
            FROM events
            WHERE processed = FALSE
            LIMIT 10
        """)

        result = await db.execute(query)
        events = result.fetchall()

        for event in events:

            print("Procesando evento:", event.event_type)

            payload = event.payload or {}

            workflow_query = text("""
                SELECT id, actions
                FROM workflows
                WHERE empresa_id = :empresa_id
                AND trigger_event = :event_type
                AND active = TRUE
            """)

            workflow_result = await db.execute(
                workflow_query,
                {
                    "empresa_id": event.empresa_id,
                    "event_type": event.event_type
                }
            )

            workflows = workflow_result.fetchall()

            for workflow in workflows:

                actions = workflow.actions

                if isinstance(actions, str):
                    actions = json.loads(actions)

                for action in actions:

                    action_type = action.get("type")

                    # LOG
                    if action_type == "log":
                        print("LOG:", payload)

                    # AGENTE IA
                    elif action_type == "agent":

                        prompt = payload.get("message")

                        if not prompt:
                            print("Evento sin message:", payload)
                            continue

                        try:
                            #result = await run_agent(prompt)
                            # DESPUÉS:
                            result = await run_agent(
                                message=prompt,
                                empresa_id=event.empresa_id,
                            )
                            print("IA RESPONSE:", result)

                        except Exception as e:
                            print("Error ejecutando agente:", str(e))

                    # WEBHOOK
                    elif action_type == "webhook":

                        url = action.get("url")
                        print("WEBHOOK:", url)

            # marcar evento como procesado
            update = text("""
                UPDATE events
                SET processed = TRUE
                WHERE id = :id
            """)

            await db.execute(update, {"id": event.id})

        await db.commit()


async def worker_loop():

    while True:
        try:
            await process_events()
        except Exception as e:
            print("Worker error:", str(e))

        await asyncio.sleep(5)