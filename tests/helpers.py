from voyvoy.agent.talker import CallBrief, Goal


def brief(owner="Roberto", contact_name="Mike Torres", goals=None, notes=None, context="Side project: a habit tracker app."):
    return CallBrief(
        owner=owner,
        contact_name=contact_name,
        contact_card="Role: PM",
        goals=goals if goals is not None else [Goal("g1", "Which login providers?")],
        context=context,
        notes=notes if notes is not None else [],
    )
