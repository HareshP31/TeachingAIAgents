"""ConversationGraph: Route -> Researcher -> Analyst -> Auditor -> HumanReview -> Notify.

Triggered by every Slack message. See docs/project-architecture-plan.md section 3.
"""

# TODO: build the LangGraph StateGraph with nodes:
#   route, researcher, analyst, auditor, human_review, notify
# and conditional edges per the state diagram in the architecture plan.
