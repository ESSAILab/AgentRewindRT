// OpenCode 1.18.31 @opencode-ai/plugin chat.message contract.
// Local run association only; this journal is not a tamper-proof audit log.
import { appendFileSync } from 'node:fs';

export default async function AgentRewindIntent({ directory }) {
  const journal = process.env.AGENTREWIND_OPENCODE_JOURNAL;
  const token = process.env.AGENTREWIND_OPENCODE_TOKEN;
  if (!journal || !token) return {};
  function record(value) {
    try {
      appendFileSync(journal, JSON.stringify({ ...value, token, directory, at: Date.now() }) + '\n', { mode: 0o600 });
    } catch {
      // Collection must not break the user's interactive agent. Missing journal
      // entries are detected by the host and never reported as complete evidence.
    }
  }
  record({ type: 'ready' });
  return {
    'chat.message': async (input, output) => {
      record({ type: 'message', session_id: input.sessionID, message_id: output.message.id });
    },
  };
}
