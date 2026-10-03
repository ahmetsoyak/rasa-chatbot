import { useEffect, useId, useMemo, useRef, useState } from "react";
import { CalendarDays, CalendarRange, Clock } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  MAX_LEAD_DAYS,
  MAX_NIGHTS,
  addDays,
  datePresets,
  describeRange,
  fromIso,
  rangeMessage,
  rangeProblem,
  relativeRange,
  toIso,
  today,
  type DateRange,
} from "@/lib/dates";

type Mode = "range" | "length" | "relative";

const MODES: { id: Mode; label: string; icon: typeof CalendarDays }[] = [
  { id: "range", label: "Pick start and end dates", icon: CalendarRange },
  { id: "length", label: "Start date + trip length", icon: CalendarDays },
  { id: "relative", label: "In X days, for Y nights", icon: Clock },
];

const NIGHT_OPTIONS = [3, 5, 7, 10, 14];
const FLEXIBLE_MESSAGE = "flexible dates";

interface DatePickerProps {
  /** `message` goes to the bot; `display` is what the user's bubble shows. */
  onSubmit: (message: string, display: string) => void;
  disabled: boolean;
}

function NumberField({ id, label, value, min, max, onChange }: {
  id: string; label: string; value: number; min: number; max: number; onChange: (n: number) => void;
}) {
  return (
    <div className="flex flex-col gap-1">
      <label htmlFor={id} className="text-xs text-muted-foreground">{label}</label>
      <input
        id={id}
        type="number"
        inputMode="numeric"
        min={min}
        max={max}
        value={Number.isFinite(value) ? value : ""}
        onChange={(e) => onChange(e.target.valueAsNumber)}
        className="h-8 w-24 rounded-md border border-input bg-transparent px-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
      />
    </div>
  );
}

function DateField({ id, label, value, min, max, onChange }: {
  id: string; label: string; value: string; min: string; max: string; onChange: (v: string) => void;
}) {
  return (
    <div className="flex flex-col gap-1">
      <label htmlFor={id} className="text-xs text-muted-foreground">{label}</label>
      <input
        id={id}
        type="date"
        value={value}
        min={min}
        max={max}
        onChange={(e) => onChange(e.target.value)}
        className="h-8 rounded-md border border-input bg-transparent px-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring dark:[color-scheme:dark]"
      />
    </div>
  );
}

function NightChips({ value, onChange }: { value: number; onChange: (n: number) => void }) {
  return (
    <div className="flex flex-wrap gap-1.5" role="group" aria-label="Common trip lengths">
      {NIGHT_OPTIONS.map((n) => (
        <Button key={n} type="button" size="xs" variant={value === n ? "default" : "outline"} aria-pressed={value === n} onClick={() => onChange(n)}>
          {n} nights
        </Button>
      ))}
    </div>
  );
}

/**
 * Quick ways to answer "What dates are you planning to travel?". Every choice
 * is converted to an explicit date range and previewed before sending.
 */
export function DatePicker({ onSubmit, disabled }: DatePickerProps) {
  const ids = useId();
  const now = useMemo(() => today(), []);
  const presets = useMemo(() => datePresets(now), [now]);
  const [mode, setMode] = useState<Mode | null>(null);
  const [start, setStart] = useState(toIso(addDays(now, 7)));
  const [end, setEnd] = useState(toIso(addDays(now, 12)));
  const [nights, setNights] = useState(5);
  const [inDays, setInDays] = useState(4);
  const panelRef = useRef<HTMLFormElement>(null);

  // The panel opens below the chips, often under the fold of the chat log.
  useEffect(() => {
    if (mode) panelRef.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [mode]);

  const minIso = toIso(now);
  const maxIso = toIso(addDays(now, MAX_LEAD_DAYS + MAX_NIGHTS));

  let range: DateRange | null = null;
  if (mode === "range") {
    const s = fromIso(start), e = fromIso(end);
    range = s && e ? { start: s, end: e } : null;
  } else if (mode === "length") {
    const s = fromIso(start);
    range = s && Number.isInteger(nights) ? { start: s, end: addDays(s, nights) } : null;
  } else if (mode === "relative") {
    range = Number.isInteger(inDays) && Number.isInteger(nights) ? relativeRange(inDays, nights, now) : null;
  }
  const problem = mode ? rangeProblem(range, now) : null;

  const submit = (r: DateRange) => onSubmit(rangeMessage(r), describeRange(r));

  return (
    <div className="flex w-full flex-col gap-2" role="group" aria-label="Choose travel dates">
      <div className="flex flex-wrap gap-2" role="group" aria-label="Ways to give your dates">
        {MODES.map(({ id, label, icon: Icon }) => (
          <Button
            key={id}
            type="button"
            size="sm"
            variant={mode === id ? "default" : "outline"}
            aria-expanded={mode === id}
            aria-controls={`${ids}-panel`}
            disabled={disabled}
            onClick={() => setMode(mode === id ? null : id)}
          >
            <Icon aria-hidden="true" />
            {label}
          </Button>
        ))}
      </div>

      <div className="flex flex-wrap gap-2" role="group" aria-label="Suggested dates">
        {presets.map((preset) => (
          <Button key={preset.id} type="button" size="sm" variant="outline" disabled={disabled} onClick={() => submit(preset.range)}>
            {preset.label}
          </Button>
        ))}
        <Button type="button" size="sm" variant="outline" disabled={disabled} onClick={() => onSubmit(FLEXIBLE_MESSAGE, "My dates are flexible")}>
          Not sure yet
        </Button>
      </div>

      {mode && (
        <form
          ref={panelRef}
          id={`${ids}-panel`}
          className="flex w-full max-w-xl flex-col gap-3 rounded-lg border bg-card p-3"
          onSubmit={(e) => {
            e.preventDefault();
            if (range && !problem) submit(range);
          }}
        >
          {mode === "range" && (
            <div className="flex flex-wrap gap-3">
              <DateField id={`${ids}-start`} label="Start date" value={start} min={minIso} max={maxIso} onChange={setStart} />
              <DateField id={`${ids}-end`} label="End date" value={end} min={start || minIso} max={maxIso} onChange={setEnd} />
            </div>
          )}
          {mode === "length" && (
            <>
              <div className="flex flex-wrap items-end gap-3">
                <DateField id={`${ids}-start`} label="Start date" value={start} min={minIso} max={maxIso} onChange={setStart} />
                <NumberField id={`${ids}-nights`} label="Nights" value={nights} min={1} max={MAX_NIGHTS} onChange={setNights} />
              </div>
              <NightChips value={nights} onChange={setNights} />
            </>
          )}
          {mode === "relative" && (
            <>
              <div className="flex flex-wrap items-end gap-3">
                <NumberField id={`${ids}-in`} label="Start in (days from today)" value={inDays} min={0} max={MAX_LEAD_DAYS} onChange={setInDays} />
                <NumberField id={`${ids}-nights`} label="Nights" value={nights} min={1} max={MAX_NIGHTS} onChange={setNights} />
              </div>
              <NightChips value={nights} onChange={setNights} />
            </>
          )}

          <p className={`text-sm ${problem ? "text-red-700 dark:text-red-400" : "font-medium"}`} role="status" aria-live="polite">
            {problem ?? (range ? describeRange(range) : "")}
          </p>
          <Button type="submit" size="sm" className="self-start" disabled={disabled || Boolean(problem)}>
            Use these dates
          </Button>
        </form>
      )}
    </div>
  );
}
