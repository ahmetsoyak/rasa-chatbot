import { useCallback, useRef, useState } from "react";
import { RasaClientError, sendMessage, type RasaBotMessage } from "@/lib/rasaClient";
import { RICH_TYPES } from "@/lib/payloads";

export interface ChatMessage {
  id: string;
  sender: "user" | "bot" | "system-error";
  text?: string;
  buttons?: RasaBotMessage["buttons"];
  custom?: Record<string, unknown>;
  /** Plain-text twin of the card just before it (hidden: the card shows it). */
  companion?: boolean;
}

/** Button payload the bot uses to ask for the browser's location. */
export const SHARE_LOCATION_PAYLOAD = "/share_location";

function newId(): string {
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

function getPosition(): Promise<GeolocationPosition> {
  return new Promise((resolve, reject) => {
    if (typeof navigator === "undefined" || !navigator.geolocation) {
      reject(new Error("unsupported"));
      return;
    }
    navigator.geolocation.getCurrentPosition(resolve, reject, {
      enableHighAccuracy: false,
      timeout: 10_000,
      maximumAge: 10 * 60_000,
    });
  });
}

export function useChat() {
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      id: newId(),
      sender: "bot",
      text: "Hi! I'm your Eco-Travel Advisor. Tell me where you'd like to go, or ask about low-carbon ways to travel.",
      buttons: [
        { title: "Plan a trip", payload: "/request_trip_planning" },
        { title: "Compare travel emissions", payload: "/ask_carbon_footprint" },
        { title: "Use my departure location", payload: SHARE_LOCATION_PAYLOAD },
      ],
    },
  ]);
  const [isSending, setIsSending] = useState(false);
  const sendingRef = useRef(false);

  const addBotNote = useCallback((text: string) => {
    setMessages((prev) => [...prev, { id: newId(), sender: "bot", text }]);
  }, []);

  /**
   * Send `message` to Rasa. `display` is what the user's bubble shows: the
   * button title for quick replies, so payloads like
   * '/inform_destination{"destination": "Lisbon"}' are never shown.
   */
  const deliver = useCallback(async (message: string, display: string) => {
    if (sendingRef.current) return;
    sendingRef.current = true;
    setMessages((prev) => [...prev, { id: newId(), sender: "user", text: display }]);
    setIsSending(true);

    try {
      const replies = await sendMessage(message);
      let afterCard = false;
      const botMessages: ChatMessage[] = replies.map((reply) => {
        const custom = reply.custom ?? reply.json_message;
        // Actions send each card followed by the same content as text (for
        // text-only channels); in this UI the card replaces that text.
        const companion = afterCard && !custom && !reply.buttons?.length && Boolean(reply.text);
        afterCard = RICH_TYPES.has(String(custom?.type));
        return { id: newId(), sender: "bot", text: reply.text, buttons: reply.buttons, custom, companion };
      });
      setMessages((prev) => [...prev, ...botMessages]);
    } catch (err) {
      const text =
        err instanceof RasaClientError ? err.message : "Something went wrong talking to the assistant.";
      setMessages((prev) => [...prev, { id: newId(), sender: "system-error", text }]);
    } finally {
      sendingRef.current = false;
      setIsSending(false);
    }
  }, []);

  /**
   * Ask the browser for the user's position and send it as
   * /share_location{"latitude":..,"longitude":..}. Coordinates are rounded to
   * ~1 km: enough to find the nearest town, less precise than needed to
   * identify a home address (data minimisation, GDPR Art. 5(1)(c)).
   */
  const shareLocation = useCallback(async () => {
    if (sendingRef.current) return;
    try {
      const pos = await getPosition();
      const latitude = Math.round(pos.coords.latitude * 100) / 100;
      const longitude = Math.round(pos.coords.longitude * 100) / 100;
      await deliver(
        `${SHARE_LOCATION_PAYLOAD}${JSON.stringify({ latitude, longitude })}`,
        "📍 Shared my location",
      );
    } catch (err) {
      const denied = typeof GeolocationPositionError !== "undefined" && err instanceof GeolocationPositionError
        && err.code === err.PERMISSION_DENIED;
      addBotNote(
        denied
          ? "No problem, location sharing is off. Just type the city you're travelling from, e.g. \"I'm travelling from Berlin\"."
          : "I couldn't get your location from this browser. Please type the city you're travelling from instead.",
      );
    }
  }, [addBotNote, deliver]);

  /** Free text from the input box. */
  const send = useCallback(
    async (rawText: string) => {
      const text = rawText.trim();
      if (text) await deliver(text, text);
    },
    [deliver],
  );

  /** A quick-reply button: location requests go through the browser first. */
  const pressButton = useCallback(
    async (payload: string, title: string) => {
      if (payload === SHARE_LOCATION_PAYLOAD) await shareLocation();
      else await deliver(payload, title);
    },
    [deliver, shareLocation],
  );

  return {
    messages,
    isSending,
    send,
    pressButton,
    shareLocation,
  };
}
