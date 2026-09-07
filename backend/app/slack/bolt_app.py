"""Slack Bolt (Socket Mode) integration.

Turns Slack messages into ConversationGraph runs (thread ID = graph thread ID),
turns file-share events into IngestionGraph runs, and posts responses /
HumanReview approval prompts back to the channel.
See docs/project-architecture-plan.md sections 3-4.
"""

# TODO: initialize the Bolt App with SLACK_BOT_TOKEN / SLACK_APP_TOKEN and
# register message + file_shared event handlers.
