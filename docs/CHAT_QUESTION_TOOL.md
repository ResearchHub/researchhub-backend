# Questions in notebook and assistant chat

Both chat modes expose `ask_question`. The agent asks one focused question
when it needs a detail or decision before proceeding. It may suggest 2–5
distinct choices; the user can always reply in their own words. Without
choices, the question is free text.

```json
{
  "question": "Who is the audience?",
  "options": ["Researchers", "General public"]
}
```

Questions are limited to 2,000 characters and choices to 200 characters each.
Malformed calls return a tool error so the model can correct them. A question
must be the only tool in its batch. If it is combined with other calls, none
of those calls execute; each gets an error asking the model to retry separately.

## Lifecycle

A successful question ends the current execution with `status: "SUCCEEDED"`
and `stop_reason: "user_input"`. The turn has successfully asked for input;
the user's broader request is awaiting their reply. No worker or usage
reservation remains occupied. The normal `turn_finished` WebSocket event
prompts clients to refetch the chat.

The question is stored in the execution's durable final output, independently
of optional traces. It is also published as a readable assistant message,
including the choices, so existing chat clients can use ordinary text replies.
The existing publication repair path recovers a missing message after a
temporary publication failure.

The chat detail response for both modes adds:

```json
{
  "pending_question": {
    "execution_id": 123,
    "question": "Who is the audience?",
    "options": ["Researchers", "General public"]
  }
}
```

`pending_question` is `null` unless the latest execution ended with a question.
Each execution also exposes `question: {"question": "...", "options": [...]}`
or `null`, preserving question history after later messages arrive.

## Submitting an answer

Use the existing `POST .../messages/` route:

- `/api/research_ai/notebook/notes/<note_id>/chats/<conversation_id>/messages/`
- `/api/research_ai/assistant/chats/<conversation_id>/messages/`

```json
{
  "message": "First-year biology students",
  "question_execution_id": 123
}
```

Send the selected option's text or the user's free-text answer as `message`.
`question_execution_id` is optional for compatibility, but question controls
should include it: the service atomically checks that it is the latest pending
question in this conversation before accepting the message. Stale, answered,
or foreign IDs return HTTP 400; an already running turn returns HTTP 409.
Existing ownership, note permissions, budget admission, and model settings apply.

An accepted reply returns HTTP 202 and starts a new execution using the prior
conversation context, including the question and tool result. Any accepted
ordinary message also clears the pending question and can change the subject.
The question is not restored automatically if the subsequent execution fails;
the human message and question remain in the conversation history.

## Frontend integration

On refresh or `turn_finished`, inspect `pending_question` and show a question
card with optional choice buttons and a free-text composer. Use the execution
ID to associate the card with its assistant message and avoid rendering the
same question twice. Keep historical cards visible but disable their answer
controls once they are no longer pending. Refetch after a stale-answer error.

No database migration or new WebSocket event is required. This backend change
provides the structured contract; choice-button rendering is frontend work.
