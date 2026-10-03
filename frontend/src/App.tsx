import { useCallback, useEffect, useId, useRef, useState } from "react";
import { Leaf, MapPin, Mic, MicOff, Send } from "lucide-react";
import { Button } from "@/components/ui/button";
import { MessageBubble } from "@/components/MessageBubble";
import { ThemeToggle } from "@/components/ThemeToggle";
import { useChat } from "@/hooks/useChat";
import { useSpeechInput } from "@/hooks/useSpeechInput";

const WAVE_HEIGHTS = [10, 18, 28, 38, 24, 44, 32, 18, 36, 26, 42, 22, 14];

function prefersReducedMotion(): boolean {
  return typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
}

function ListeningWaveform() {
  return (
    <div className="pointer-events-none absolute inset-0 flex items-center gap-3 rounded-md bg-primary px-3 text-primary-foreground">
      <Mic className="size-4 shrink-0" aria-hidden="true" />
      <div className="flex h-7 flex-1 items-center justify-center gap-1" aria-hidden="true">
        {WAVE_HEIGHTS.map((height, index) => (
          <span
            key={index}
            className="w-1 rounded-full bg-primary-foreground motion-safe:animate-[listening-wave_900ms_ease-in-out_infinite]"
            style={{ height, animationDelay: `${index * -70}ms` }}
          />
        ))}
      </div>
      <span className="text-xs font-medium">Listening…</span>
      <span className="sr-only" role="status">Listening for your message.</span>
    </div>
  );
}

function App() {
  const { messages, isSending, send, pressButton, shareLocation } = useChat();
  const [draft, setDraft] = useState("");
  const scrollEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const inputId = useId();
  const hintId = useId();
  const lastBotText = [...messages].reverse().find((message) => message.sender === "bot" && message.text)?.text?.toLowerCase() ?? "";
  const placeholder = lastBotText.includes("what dates")
    ? "When are you travelling?"
    : lastBotText.includes("budget")
      ? "What is your budget?"
      : lastBotText.includes("how much should low emissions")
        ? "How important is low carbon?"
        : "Where would you like to go?";

  const appendTranscript = useCallback((text: string) => {
    setDraft((d) => (d ? `${d} ${text}` : text));
    inputRef.current?.focus();
  }, []);
  const speech = useSpeechInput(appendTranscript);

  useEffect(() => {
    scrollEndRef.current?.scrollIntoView({ behavior: prefersReducedMotion() ? "auto" : "smooth", block: "end" });
  }, [messages, isSending]);

  // Keep keyboard and screen-reader users in the input after every turn.
  useEffect(() => {
    if (!isSending) inputRef.current?.focus();
  }, [isSending]);

  const handleSend = () => {
    if (!draft.trim() || isSending) return;
    void send(draft);
    setDraft("");
  };

  return (
    <div className="flex h-dvh overflow-hidden flex-col bg-background text-foreground">
      <a
        href={`#${inputId}`}
        className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded-md focus:bg-background focus:px-3 focus:py-2 focus:ring-2 focus:ring-ring"
      >
        Skip to message box
      </a>
      <header className="flex items-center justify-between border-b px-4 py-3">
        <div className="flex items-center gap-2">
          <span
            className="flex size-8 items-center justify-center rounded-full bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300"
            aria-hidden="true"
          >
            <Leaf className="size-4" />
          </span>
          <div>
            <h1 className="text-sm font-semibold leading-none">Eco-Travel Advisor</h1>
            <p className="text-xs text-muted-foreground">Low-carbon trip planning assistant</p>
          </div>
        </div>
        <ThemeToggle />
      </header>

      <main className="flex min-h-0 flex-1 flex-col">
        <div className="relative min-h-0 flex-1 overflow-y-auto">
          <div
            className="mx-auto flex max-w-4xl flex-col gap-4 p-4"
            role="log"
            aria-live="polite"
            aria-relevant="additions"
            aria-label="Conversation with the Eco-Travel Advisor"
          >
            {messages.map((message, index) => (
              <MessageBubble
                key={message.id}
                message={message}
                disabled={isSending}
                isLatest={index === messages.length - 1}
                onButtonClick={(payload, title) => void pressButton(payload, title)}
              />
            ))}
          </div>
          <div className="mx-auto max-w-4xl px-4 pb-4">
            <p role="status" aria-live="polite" className="text-xs text-muted-foreground">
              {isSending ? "Eco-Travel Advisor is typing…" : ""}
            </p>
            <div ref={scrollEndRef} />
          </div>
        </div>
      </main>

      <footer className="border-t p-3">
        <form
          className="mx-auto flex max-w-4xl items-center gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            handleSend();
          }}
        >
          <label htmlFor={inputId} className="sr-only">
            Message the Eco-Travel Advisor
          </label>
          <Button
            type="button"
            variant="outline"
            size="icon"
            onClick={() => void shareLocation()}
            disabled={isSending}
            aria-label="Share my location to calculate journeys from here"
            title="Share my location"
          >
            <MapPin className="size-4" aria-hidden="true" />
          </Button>
          <div className="relative min-w-0 flex-1">
            <input
              ref={inputRef}
              id={inputId}
              type="text"
              value={draft}
              autoComplete="off"
              aria-describedby={hintId}
              onChange={(e) => setDraft(e.target.value)}
              placeholder={placeholder}
              className={`w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm shadow-xs outline-none placeholder:text-muted-foreground focus-visible:ring-2 focus-visible:ring-ring ${speech.listening ? "caret-transparent text-transparent" : ""}`}
            />
            {speech.listening && <ListeningWaveform />}
          </div>
          {speech.supported && (
            <Button
              type="button"
              variant={speech.listening ? "default" : "outline"}
              size="icon"
              onClick={speech.toggle}
              aria-pressed={speech.listening}
              aria-label={speech.listening ? "Stop voice input" : "Speak your message"}
              title={speech.listening ? "Stop voice input" : "Speak your message"}
            >
              {speech.listening ? <MicOff className="size-4" aria-hidden="true" /> : <Mic className="size-4" aria-hidden="true" />}
            </Button>
          )}
          <Button type="submit" disabled={isSending || !draft.trim()} size="icon" aria-label="Send message">
            <Send className="size-4" aria-hidden="true" />
          </Button>
        </form>
        <p id={hintId} className="mx-auto mt-1 max-w-4xl text-[11px] text-muted-foreground" aria-live="polite">
          {speech.error ??
            "Your location is only used for this chat. Ask \"what do you do with my data?\" for details."}
        </p>
      </footer>
    </div>
  );
}

export default App;
