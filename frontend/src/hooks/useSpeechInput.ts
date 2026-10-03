/**
 * Optional voice input via the Web Speech API (Chrome, Edge, Safari). The
 * transcript is placed in the text box for the user to check before sending,
 * rather than sent straight away, so recognition errors can be corrected.
 * Returns `supported: false` where the API is missing (e.g. Firefox), and
 * the microphone button is then not rendered.
 */
import { useCallback, useEffect, useRef, useState } from "react";

interface SpeechRecognitionResultLike {
  0: { transcript: string };
  isFinal: boolean;
}
interface SpeechRecognitionEventLike {
  resultIndex: number;
  results: ArrayLike<SpeechRecognitionResultLike>;
}
interface SpeechRecognitionLike {
  lang: string;
  interimResults: boolean;
  continuous: boolean;
  onresult: ((e: SpeechRecognitionEventLike) => void) | null;
  onerror: ((e: { error: string }) => void) | null;
  onend: (() => void) | null;
  start(): void;
  stop(): void;
}
type SpeechRecognitionCtor = new () => SpeechRecognitionLike;

function getRecognitionCtor(): SpeechRecognitionCtor | undefined {
  if (typeof window === "undefined") return undefined;
  const w = window as unknown as { SpeechRecognition?: SpeechRecognitionCtor; webkitSpeechRecognition?: SpeechRecognitionCtor };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition;
}

export function useSpeechInput(onTranscript: (text: string) => void, lang = "en-GB") {
  const [listening, setListening] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const recRef = useRef<SpeechRecognitionLike | null>(null);
  const supported = getRecognitionCtor() !== undefined;

  useEffect(() => () => recRef.current?.stop(), []);

  const toggle = useCallback(() => {
    if (listening) {
      recRef.current?.stop();
      return;
    }
    const Ctor = getRecognitionCtor();
    if (!Ctor) return;
    const rec = new Ctor();
    rec.lang = lang;
    rec.interimResults = false;
    rec.continuous = false;
    rec.onresult = (e) => {
      const result = e.results[e.resultIndex];
      if (result?.isFinal) onTranscript(result[0].transcript);
    };
    rec.onerror = (e) => {
      setError(e.error === "not-allowed" ? "Microphone access was blocked." : "I couldn't hear that. Please try again or type.");
    };
    rec.onend = () => setListening(false);
    recRef.current = rec;
    setError(null);
    setListening(true);
    rec.start();
  }, [lang, listening, onTranscript]);

  return { supported, listening, error, toggle };
}
