/**
 * Thin client for the Rasa REST channel.
 *
 * Endpoint: POST {RASA_URL}/webhooks/rest/webhook
 * Body:     { sender: string; message: string }
 * Response: an array of bot message objects, each optionally carrying
 *           text, an image, quick-reply buttons, and/or a custom JSON
 *           payload (`custom`) used for rich cards (see payloads.ts).
 */

const RASA_URL: string =
  (import.meta.env.VITE_RASA_URL as string | undefined) ?? "http://localhost:5005";

let senderId: string | undefined;

/** Keep one Rasa conversation for the current page session. */
export function getSenderId(): string {
  if (typeof window === "undefined") return "server";
  if (!senderId) {
    senderId =
      typeof crypto !== "undefined" && "randomUUID" in crypto
        ? crypto.randomUUID()
        : `sender-${Date.now()}-${Math.random().toString(36).slice(2)}`;
  }
  return senderId;
}

/** A single quick-reply button, as sent by Rasa's `buttons` response field. */
export interface RasaButton {
  title: string;
  payload: string;
}

/**
 * One message object as returned by the Rasa REST channel.
 * Rasa may send several of these per user turn.
 */
export interface RasaBotMessage {
  recipient_id?: string;
  text?: string;
  image?: string;
  buttons?: RasaButton[];
  /** Arbitrary structured payload — used here for cards/carousels/handover flags. */
  custom?: Record<string, unknown>;
  json_message?: Record<string, unknown>;
}

export class RasaClientError extends Error {}

/**
 * Send a message to the Rasa REST webhook and return the bot's replies.
 * Throws RasaClientError on network failure or a non-2xx response so
 * callers can render an inline error instead of crashing.
 */
export async function sendMessage(message: string): Promise<RasaBotMessage[]> {
  const sender = getSenderId();

  let response: Response;
  try {
    response = await fetch(`${RASA_URL}/webhooks/rest/webhook`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sender, message }),
    });
  } catch (err) {
    throw new RasaClientError(
      `Could not reach the assistant at ${RASA_URL}. Is the Rasa server running? (${
        err instanceof Error ? err.message : String(err)
      })`,
    );
  }

  if (!response.ok) {
    throw new RasaClientError(
      `Assistant server responded with status ${response.status} ${response.statusText}`,
    );
  }

  try {
    const data = (await response.json()) as unknown;
    if (!Array.isArray(data)) {
      throw new RasaClientError("Unexpected response shape from Rasa (expected an array).");
    }
    return data as RasaBotMessage[];
  } catch (err) {
    if (err instanceof RasaClientError) throw err;
    throw new RasaClientError("Failed to parse the assistant's response as JSON.");
  }
}

export { RASA_URL };
